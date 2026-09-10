$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build:local
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Output 'Setup complete. Open Start-Flykeeper.cmd to launch the app.'
