@echo off
REM Record the real AI answers for the 5 demo scenarios (decision D14). Run once the Gemini quota has reset.
cd /d "%~dp0..\.."
uv run python scripts\record_demo_answers.py
git add src\agentguard\web\demo_ai_answers.jsonl
git commit -m "Demo: recorded real AI answers for the 5 scripted scenarios (D14)"
git push
echo.
echo Done. Copy the [OK / [FAIL lines to Claude.
pause
