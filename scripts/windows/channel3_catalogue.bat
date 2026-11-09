@echo off
REM Build the demo catalogue from real Channel3 products (a few search credits). Then commit it.
cd /d "%~dp0..\.."
uv run python scripts\channel3_catalogue.py
git add src\agentguard\web\channel3_catalogue.json
git commit -m "Demo catalogue from real Channel3 products (snapshot)"
echo.
echo Done. Copy the [OK / [FAIL lines to Claude.
pause
