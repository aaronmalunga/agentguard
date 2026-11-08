@echo off
REM AI evaluation: DEV set again (only previously failed calls are re-asked), then the HELD-OUT set (logged look #2).
cd /d "%~dp0..\.."
echo === 1/3  DEV set with AI (re-asks only failed calls) ===
uv run python eval\run_eval.py --ai
echo.
echo === 2/3  HELD-OUT set with AI (look #2, about 5 minutes) ===
uv run python eval\run_eval.py --ai --split heldout --reason "Held-out look #2: rules+detector+AI (gemini-3.5-flash-lite), after dev evaluation; detector frozen at 5e48324"
echo.
echo === 3/3  Commit results and push ===
git add evidence
git commit -m "AI evaluation: dev rerun + held-out look #2 (Gemini answers cached)"
git push
echo.
echo Done. Tell Claude "done" - it reads the results from the saved files.
pause
