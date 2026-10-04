# Creates the "NK61P Live" desktop shortcut. Re-run this if you move the NK61P folder.
$root = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw -ErrorAction Stop).Source
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NK61P Live.lnk'

$sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sh.TargetPath = $pythonw
$sh.Arguments = '"' + (Join-Path $root 'nk61p.py') + '"'
$sh.WorkingDirectory = $root
$sh.IconLocation = (Join-Path $root 'nk61p.ico') + ',0'
$sh.Description = 'NK61P multimeter live display and logger'
$sh.Save()
Write-Output "Created $lnk"
