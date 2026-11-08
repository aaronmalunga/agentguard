@echo off
REM Quick AI check only (about 30 seconds). Output also saved to evidence\ai_smoke_last.txt for Claude.
cd /d "%~dp0..\.."
uv run python scripts\smoke_ai.py
pause
