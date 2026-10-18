@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
rem The launcher is intentionally credential-free and always exercises offline mode.
rem Use the documented CLI directly when you explicitly want a live mailbox run.
set "IMAP_USERNAME=your_offline_username"
set "IMAP_PASSWORD=your_offline_password"
set "GEMINI_API_KEY=your_offline_key"

echo Starting Agent Job Tracker in offline-safe mode...
python -m agent_job_tracker
if errorlevel 1 (
    echo.
    echo Agent Job Tracker failed to start. Check that Python 3.10+ is installed.
)
pause
