# Build both .exe artifacts in order.
# Run from the repo root:  pwsh ./build.ps1
$ErrorActionPreference = "Stop"

Write-Host "==> Installing build deps..." -ForegroundColor Cyan
python -m pip install --upgrade pip --quiet
python -m pip install --upgrade pyinstaller --quiet
python -m pip install -e ".[dev]" --quiet

Write-Host "==> Running test suite..." -ForegroundColor Cyan
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed; aborting build." -ForegroundColor Red
    exit 1
}

Write-Host "==> Cleaning dist/ and build/..." -ForegroundColor Cyan
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue

Write-Host "==> Building OIK.exe..." -ForegroundColor Cyan
pyinstaller --clean --noconfirm OIK.spec

if (-not (Test-Path "dist/OIK.exe")) {
    Write-Host "Main .exe not produced." -ForegroundColor Red
    exit 1
}

Write-Host "==> Building OIK_Setup.exe..." -ForegroundColor Cyan
pyinstaller --clean --noconfirm OIK_Setup.spec

Write-Host ""
Write-Host "Done. Artifacts:" -ForegroundColor Green
Get-ChildItem dist | Format-Table Name, Length, LastWriteTime
