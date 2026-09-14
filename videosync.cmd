@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0videosync.py" %*
) else (
    python "%~dp0videosync.py" %*
)
exit /b %errorlevel%
