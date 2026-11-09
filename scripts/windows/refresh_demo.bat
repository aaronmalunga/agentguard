@echo off
REM Rebuild the demo on well-known Channel3 products, re-record the 5 AI answers, run the live check, push.
cd /d "%~dp0..\.."
uv sync
echo === 1/3  Pick real products (most shops wins) ===
uv run python scripts\channel3_catalogue.py
echo.
echo === 2/3  Record AI answers for the 5 demo scenarios ===
uv run python scripts\record_demo_answers.py
echo.
echo === 3/3  Live check through the web app (PayPal sandbox + AI + Channel3) ===
uv run python scripts\smoke_api.py
git add src\agentguard\web\channel3_catalogue.json src\agentguard\web\demo_ai_answers.jsonl spike\results
git commit -m "Demo rebuilt on multi-shop Channel3 products: AI answers re-recorded, live web-app check"
git push
echo.
echo Done. Copy everything from "=== 1/3" down to Claude.
pause
