"""NK61P live reader: web dashboard + CSV logger.

    python nk61p.py                    # auto-detect the CH340 port, open http://127.0.0.1:8061
    python nk61p.py --port COM8 --log  # start logging to CSV immediately
    python nk61p.py --cli              # no web UI, just print readings
    python nk61p.py --replay research/frames.log   # demo without the meter
"""
from __future__ import annotations

import argparse
import csv
import json
import queue
import re
import sys
import threading
import time
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nk61p_protocol import FrameSplitter, decode

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
CH340_VID_PID = (0x1A86, 0x7523)

CSV_FIELDS = ["timestamp", "elapsed_s", "display", "value", "base_value",
              "prefix", "unit", "mode", "flags", "bar", "raw"]


def find_port() -> str | None:
    from serial.tools import list_ports
    for p in list_ports.comports():
        if (p.vid, p.pid) == CH340_VID_PID:
            return p.device
    return None


class Hub:
    """Fan-out of readings/status to SSE clients, plus the CSV logger."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[queue.Queue] = []
        self.status = {"state": "starting", "port": None, "detail": ""}
        self.last: dict | None = None
        self._log_file = None
        self._log_writer = None
        self.log_path: Path | None = None
        self.log_rows = 0
        self._log_t0 = 0.0

    # --- pub/sub -------------------------------------------------------
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def _broadcast(self, event: str, data: dict) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass  # slow client; it will catch up on the next reading

    def set_status(self, state: str, port: str | None = None, detail: str = "") -> None:
        self.status = {"state": state, "port": port, "detail": detail}
        self._broadcast("status", self.status)

    # --- readings ------------------------------------------------------
    def publish(self, frame: bytes) -> None:
        r = decode(frame)
        now = time.time()
        payload = asdict(r) | {"mode": r.mode, "t": now}
        self.last = payload
        with self._lock:
            if self._log_writer:
                self._log_writer.writerow({
                    "timestamp": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                    "elapsed_s": f"{now - self._log_t0:.3f}",
                    "display": r.display,
                    "value": "" if r.value is None else r.value,
                    "base_value": "" if r.base_value is None else f"{r.base_value:.9g}",
                    "prefix": r.prefix, "unit": r.unit, "mode": r.mode,
                    "flags": " ".join(r.flags), "bar": r.bar, "raw": r.raw,
                })
                self.log_rows += 1
                if self.log_rows % 20 == 0:
                    self._log_file.flush()
        payload["log"] = self.log_info()
        self._broadcast("reading", payload)

    # --- logging -------------------------------------------------------
    def log_info(self) -> dict:
        return {"active": self._log_writer is not None,
                "file": self.log_path.name if self.log_path else None,
                "rows": self.log_rows}

    def start_log(self) -> dict:
        with self._lock:
            if self._log_writer is None:
                LOG_DIR.mkdir(exist_ok=True)
                self.log_path = LOG_DIR / f"nk61p_{datetime.now():%Y%m%d_%H%M%S}.csv"
                self._log_file = open(self.log_path, "w", newline="", encoding="utf-8")
                self._log_writer = csv.DictWriter(self._log_file, CSV_FIELDS)
                self._log_writer.writeheader()
                self.log_rows = 0
                self._log_t0 = time.time()
        info = self.log_info()
        self._broadcast("log", info)
        return info

    def stop_log(self) -> dict:
        with self._lock:
            if self._log_writer is not None:
                self._log_file.close()
                self._log_file = self._log_writer = None
        info = self.log_info()
        self._broadcast("log", info)
        return info


# --- sources -------------------------------------------------------------

def serial_loop(hub: Hub, port_arg: str | None, stop: threading.Event) -> None:
    import serial
    while not stop.is_set():
        port = port_arg or find_port()
        if not port:
            hub.set_status("waiting", None, "Meter not found - plug it in and turn on USB mode")
            stop.wait(2)
            continue
        try:
            with serial.Serial(port, 2400, timeout=0.05) as s:
                # The CH340 cable needs DTR high to power its side of the link.
                s.dtr, s.rts = True, False
                hub.set_status("connected", port)
                splitter = FrameSplitter()
                last_frame = time.time()
                while not stop.is_set():
                    # Read only what has arrived so each frame gets its own timestamp.
                    for frame in splitter.feed(s.read(s.in_waiting or 1)):
                        if hub.status["state"] != "connected":
                            hub.set_status("connected", port)
                        hub.publish(frame)
                        last_frame = time.time()
                    if time.time() - last_frame > 3:
                        hub.set_status("no-data", port, "Port open but no data - press REL/USB to enable USB output")
                        last_frame = time.time()
        except (serial.SerialException, OSError) as e:
            hub.set_status("error", port, str(e))
            stop.wait(2)


def replay_loop(hub: Hub, path: str, stop: threading.Event) -> None:
    lines = [l.split(None, 1) for l in Path(path).read_text().splitlines() if l.strip()]
    hub.set_status("replay", path)
    while not stop.is_set():
        prev_t = None
        for t, hx in lines:
            t = float(t)
            if prev_t is not None:
                stop.wait(min(t - prev_t, 2.0))
            prev_t = t
            if stop.is_set():
                return
            hub.publish(bytes.fromhex(hx.replace(" ", "")))


# --- web -----------------------------------------------------------------

# guide.html is authored as a page fragment (it's also published as a claude.ai
# artifact, which supplies its own skeleton), so wrap it for local serving.
GUIDE_SKELETON = (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                  b'<meta name="viewport" content="width=device-width, initial-scale=1">'
                  b'<meta name="color-scheme" content="light dark">'
                  b'<meta name="darkreader-lock">'
                  b'<style>[hidden]{display:none!important}body{margin:0}img{max-width:100%}</style>'
                  b'</head><body>')


def make_handler(hub: Hub, shutdown):
    dashboard = HERE / "dashboard.html"
    guide = HERE / "guide.html"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console readable
            pass

        def _send(self, body: bytes, ctype: str, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj).encode(), "application/json", code)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(dashboard.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/guide":
                self._send(GUIDE_SKELETON + guide.read_bytes() + b"</body></html>", "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json({"status": hub.status, "last": hub.last, "log": hub.log_info()})
            elif self.path == "/events":
                self._sse()
            elif m := re.fullmatch(r"/logs/(nk61p_\d{8}_\d{6}\.csv)", self.path):
                f = LOG_DIR / m.group(1)
                if not f.exists():
                    return self._json({"error": "not found"}, 404)
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path == "/api/log/start":
                self._json(hub.start_log())
            elif self.path == "/api/log/stop":
                self._json(hub.stop_log())
            elif self.path == "/api/quit":
                # The desktop launcher runs without a console, so the page is the off switch.
                self._json({"ok": True})
                hub.set_status("offline", None, "Stopped. Use the desktop icon to start again.")
                threading.Thread(target=shutdown, daemon=True).start()
            else:
                self._json({"error": "not found"}, 404)

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = hub.subscribe()
            try:
                self.wfile.write(f"event: status\ndata: {json.dumps(hub.status)}\n\n".encode())
                self.wfile.write(f"event: log\ndata: {json.dumps(hub.log_info())}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        msg = ": keepalive\n\n"
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


def run_cli(hub: Hub) -> None:
    q = hub.subscribe()
    last = None
    while True:
        msg = q.get()
        event, data = msg.split("\n", 2)[:2]
        d = json.loads(data[6:])
        if event == "event: status":
            print(f"[{d['state']}] {d.get('port') or ''} {d.get('detail') or ''}", file=sys.stderr)
        elif event == "event: reading":
            line = f"{d['display']:>8} {d['prefix']}{d['unit']:<3} {d['mode']:<12} {' '.join(d['flags'])}"
            if line != last:
                print(f"{datetime.now():%H:%M:%S.%f}"[:-3], line, flush=True)
                last = line


def already_running(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url + "api/state", timeout=1) as r:
            return "status" in json.load(r)
    except (OSError, ValueError):
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="NKTECH NK61P live reader / logger")
    ap.add_argument("--port", help="serial port (default: auto-detect CH340)")
    ap.add_argument("--http-port", type=int, default=8061)
    ap.add_argument("--log", action="store_true", help="start CSV logging immediately")
    ap.add_argument("--cli", action="store_true", help="print readings instead of serving the dashboard")
    ap.add_argument("--replay", metavar="FRAMES_LOG", help="replay a captured frames.log instead of the meter")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.http_port}/"
    if not args.cli and already_running(url):
        # Double-clicking the launcher again just brings the dashboard back up.
        webbrowser.open(url)
        return

    hub = Hub()
    stop = threading.Event()
    source = (lambda: replay_loop(hub, args.replay, stop)) if args.replay \
        else (lambda: serial_loop(hub, args.port, stop))
    threading.Thread(target=source, daemon=True).start()
    if args.log:
        print("Logging to", hub.start_log()["file"], file=sys.stderr)

    try:
        if args.cli:
            run_cli(hub)
        else:
            server = ThreadingHTTPServer(("127.0.0.1", args.http_port),
                                         make_handler(hub, lambda: server.shutdown()))
            server.daemon_threads = True
            print(f"NK61P dashboard: {url}  (Ctrl+C to quit)", file=sys.stderr)
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        hub.stop_log()


if __name__ == "__main__":
    main()
