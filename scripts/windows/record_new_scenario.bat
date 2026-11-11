@echo off
REM Record the real AI answer for the new "Mislabelled listing" scenario only (11 Nov). Keeps all earlier answers.
cd /d "%~dp0..\.."
git pull --rebase origin main
uv run python scripts\record_demo_answers.py --add mislabelled
git add src\agentguard\web\demo_ai_answers.jsonl
git commit -m "Demo: recorded real AI answer for the Mislabelled listing scenario (D14)"
git push
echo.
echo Done. Copy the [OK / [FAIL line to Claude.
pause
