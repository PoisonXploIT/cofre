@echo off
rem Ayudante de credenciales de git para COFRE (paso 7.2).
rem Configura: git config --global credential.helper "C:/Users/Sammi/AI/cofre/git-credential-cofre.cmd"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m cofre.git_helper %*
) else (
  python -m cofre.git_helper %*
)
