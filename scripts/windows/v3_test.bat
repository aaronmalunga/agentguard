@echo off
REM Catalogue v3 (fresh, test-only) + regression checks. About 25-30 minutes. Leave it running.
REM 1) Gemma rewrites (with retries) 2) build + FREEZE in git before any run 3) v3 with AI (logged look)
REM 4) dev + held-out with AI (look #3: regression check after the v2 fixes) 5) commit + push
cd /d "%~dp0..\.."
echo === 1/5  Gemma paraphrases (retries on Google server errors) ===
uv run python eval\attacks\paraphrase.py v3
echo.
echo === 2/5  Build and freeze v3 ===
cd eval\attacks
uv run python build_catalogue_v3.py
cd ..\..
git add eval\attacks\v3
git commit -m "Freeze catalogue v3 (test-only, Gemma paraphrases) before any run"
echo.
echo === 3/5  v3 with AI (logged look) ===
uv run python eval\run_eval.py --ai --split v3 --reason "Catalogue v3 pre-registered run: tests the disclosed v2 fixes and new attack styles"
echo.
echo === 4/5  Regression: dev, then held-out look #3, with AI ===
uv run python eval\run_eval.py --ai
uv run python eval\run_eval.py --ai --split heldout --reason "Held-out look #3: regression check after disclosed v2-informed fixes (56d3767)"
echo.
echo === 5/5  Commit results and push ===
git add evidence
git commit -m "Catalogue v3 results + regression (dev, held-out look #3)"
git push
echo.
echo Done. Tell Claude "done".
pause
