"""Regenerate the README screenshots.

Start a replay first:  python nk61p.py --replay research/demo_decay.frames.log --http-port 8062 --no-browser
Then run:              python tools/screenshots.py
Needs Playwright (pip install playwright) and a local Chrome.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"
DOCS.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8062"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1280, "height": 860}, color_scheme="dark", device_scale_factor=2)

    page.goto(BASE + "/")
    page.select_option("#window", "30")
    # Wait until the chart holds both the ~5.2 V plateau and the decay back towards 0 V.
    page.wait_for_function("() => typeof series !== 'undefined' && series.some(p => p.v > 4)"
                           " && series.some(p => p.v > 0.3 && p.v < 2)", timeout=120000)
    page.wait_for_timeout(3000)
    page.screenshot(path=DOCS / "dashboard.png")

    page.goto(BASE + "/guide")
    page.wait_for_timeout(1500)
    page.locator("#mode-ma").scroll_into_view_if_needed()
    page.evaluate("document.getElementById('mode-ma').scrollIntoView({block: 'start'})")
    page.wait_for_timeout(1200)
    page.screenshot(path=DOCS / "guide.png")
    browser.close()

print("wrote", DOCS / "dashboard.png", DOCS / "guide.png")
