@echo off
REM Day 1 close: live PayPal sandbox check through the product code, then commit the result and push.
REM Double-click this file, or run it from any folder. Safe to run again.
cd /d "%~dp0..\.."
echo.
echo === 1/3  Checking uv (Python tool) ===
where uv >nul 2>nul || pip install uv
echo.
echo === 2/3  Live PayPal SANDBOX check (needs ..\.env with sandbox keys) ===
uv run python scripts\smoke_gateway.py
echo.
echo === 3/3  Commit the result file and push everything to GitHub ===
git add spike\results
git commit -m "Gateway live sandbox smoke results"
git push
echo.
echo Done. Copy the lines above that start with [OK or [FAIL and the "steps as expected" line to Claude.
pause
