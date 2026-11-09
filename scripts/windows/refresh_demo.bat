@echo off
REM After the catalogue changed: re-record the 5 demo AI answers, then the live check (PayPal sandbox + AI + Channel3), then push.
cd /d "%~dp0..\.."
uv sync
echo === 1/2  Record AI answers for the 5 demo scenarios ===
uv run python scripts\record_demo_answers.py
echo.
echo === 2/2  Live check through the web app ===
uv run python scripts\smoke_api.py
git add src\agentguard\web\demo_ai_answers.jsonl spike\results
git commit -m "Demo on real Channel3 products: re-recorded AI answers + live web-app check"
git push
echo.
echo Done. Copy everything from "=== 1/2" down to Claude.
pause
