@echo off
REM Push all committed work to GitHub.
cd /d "%~dp0..\.."
git push
pause
