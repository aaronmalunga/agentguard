@echo off
REM Push all committed work to GitHub.
cd /d "%~dp0..\.."
REM Pull first (rebase your local commits on top of what Claude pushed), then push.
git pull --rebase origin main || (echo. & echo Pull failed: paste this window to Claude before doing anything else. & pause & exit /b 1)
git push
pause
