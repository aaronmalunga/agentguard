@echo off
REM Catalogue v2 (harder, test-only): 1) Gemma rewrites the attack sentences, 2) build + FREEZE (commit) before any run,
REM 3) run all three configurations on v2 (logged look), 4) commit results and push. About 12-15 minutes.
cd /d "%~dp0..\.."
echo === 1/4  Gemma paraphrases ===
uv run python eval\attacks\paraphrase_v2.py
echo.
echo === 2/4  Build and freeze v2 (committed BEFORE it is run) ===
cd eval\attacks
uv run python build_catalogue_v2.py
cd ..\..
git add eval\attacks\v2
git commit -m "Freeze catalogue v2 (test-only, Gemma paraphrases) before any run"
echo.
echo === 3/4  Run rules, detector and AI on v2 (logged look) ===
uv run python eval\run_eval.py --ai --split v2 --reason "Catalogue v2 first and only pre-registered run: harder, independently worded, test-only"
echo.
echo === 4/4  Commit results and push ===
git add evidence
git commit -m "Catalogue v2 results (look logged)"
git push
echo.
echo Done. Tell Claude "done".
pause
