@echo off
REM Live AI check (Gemini): key works, plain English -> rules, 3 intent checks. Then the dev evaluation with AI.
cd /d "%~dp0..\.."
where uv >nul 2>nul || pip install uv
echo === 1/3  AI smoke test ===
uv run python scripts\smoke_ai.py
echo.
echo === 2/3  Evaluation on the DEV set with the AI layer (about 10 minutes on the free tier) ===
uv run python eval\run_eval.py --ai
echo.
echo === 3/3  Commit results and push ===
git add evidence
git commit -m "AI layer: live smoke + dev evaluation with Gemini (answers cached for replay)"
git push
echo.
echo Done. Copy everything from "model:" down to "saved" to Claude.
pause
