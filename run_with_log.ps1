# Optional: run main_v6 with PowerShell tee (program also writes logs/ by default)
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
if (Test-Path ".\.venv\Scripts\python.exe") {
    .\.venv\Scripts\python.exe -u main_v6.py 2>&1 | Tee-Object -FilePath "run.log"
} else {
    python -u main_v6.py 2>&1 | Tee-Object -FilePath "run.log"
}
