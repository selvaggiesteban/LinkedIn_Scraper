# setup.ps1 — LinkedIn Scraper Auth Launcher (Windows)
# Run once to authenticate the LinkedIn MCP server interactively.
$ErrorActionPreference = "Stop"

# 1. Check Python is available
$pyVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python not found. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $pyVersion" -ForegroundColor Green

# 2. Invoke the interactive auth assistant
python auth_assistant.py --interactive
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[SUCCESS] Login OK. You can now run: python linkedin_scraper.py" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[FAIL] Login failed. Check output/auth_assistant.log" -ForegroundColor Red
    exit 1
}
