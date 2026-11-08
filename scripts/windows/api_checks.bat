@echo off
REM Live check of the web API: real PayPal sandbox + real AI model. Then commit the result.
cd /d "%~dp0..\.."
where uv >nul 2>nul || pip install uv
uv sync
uv run python scripts\smoke_api.py
git add spike\results
git commit -m "Live sandbox check: web API (5 scenarios, void, receipt, audit chain)"
echo.
echo Done. Copy the [OK / [FAIL lines, the steps-as-expected line and the AGENTGUARD_VAULT_ID line (if shown) into your .env, then tell Claude.
pause
