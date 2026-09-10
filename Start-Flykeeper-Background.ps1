$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$flyPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
Start-Process -FilePath $flyPython -WorkingDirectory $PSScriptRoot -ArgumentList 'launcher.py --background' -WindowStyle Hidden
