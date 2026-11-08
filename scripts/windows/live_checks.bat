@echo off
REM Live PayPal SANDBOX checks through the product code, then commit the results and push everything.
cd /d "%~dp0..\.."
where uv >nul 2>nul || pip install uv
echo === 1/3  Gateway check ===
uv run python scripts\smoke_gateway.py
echo.
echo === 2/3  Full flow check (approve, ask-first, hold + void, block) ===
uv run python scripts\smoke_flow.py
echo.
echo === 3/3  Commit results and push ===
git add spike\results
git commit -m "Live sandbox checks: gateway + full flow"
git push
echo.
echo Done. Copy the [OK / [FAIL lines and the "steps as expected" lines to Claude.
pause
