@echo off
REM Pre-registered agent experiment (eval\agent_runs\PLAN.md): a real Strands agent through the AgentGuard MCP server,
REM against the live demo. Needs GEMINI_API_KEY and AGENTGUARD_AGENT_MODEL in your .env (agent model must differ
REM from the guard's). Takes about 30-40 minutes for 40 runs. Then commits the evidence file.
cd /d "%~dp0..\.."
set GROUPS=%1
if "%GROUPS%"=="" set GROUPS=G1,G2,G3,G4
where uv >nul 2>nul || pip install uv
git pull
uv sync --all-extras
REM The agent gets its own environment: Strands needs an older google-genai than the guard uses.
uv run --isolated --with-editable ".[agent]" --with "strands-agents[gemini]" --with python-dotenv python scripts\agent_runs.py --groups %GROUPS% --runs 10
git add evidence\agent_runs
git commit -m "Agent experiment: 40 pre-registered runs (Strands + AgentGuard MCP)"
echo.
echo Done. Copy the Summary line into the chat, then push (scripts\windows\push_only.bat) or tell Claude.
pause
