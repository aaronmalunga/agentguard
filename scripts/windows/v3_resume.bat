@echo off
REM Resume catalogue v3 AFTER it was frozen (608d01d): evaluation only. Saved AI answers are reused.
REM About 15-25 minutes. Leave it running. Google's free tier sometimes errors; failed calls become "ask" and are logged.
cd /d "%~dp0..\.."
echo === 1/3  v3 with AI (logged look) ===
uv run python eval\run_eval.py --ai --split v3 --reason "Catalogue v3 pre-registered run (resumed after an interrupted first attempt; v3 frozen at 608d01d)"
echo.
echo === 2/3  Regression: dev, then held-out look #3 ===
uv run python eval\run_eval.py --ai
uv run python eval\run_eval.py --ai --split heldout --reason "Held-out look #3: regression check after disclosed v2-informed fixes (56d3767)"
echo.
echo === 3/3  Commit results and push ===
git add evidence
git commit -m "Catalogue v3 results + regression (dev, held-out look #3)"
git push
echo.
echo Done. Tell Claude "done".
pause
