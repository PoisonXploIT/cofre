@echo off
rem Sonda de mensajeria nativa: lanza host.py con el python del repo, sin rutas fijas.
cd /d "%~dp0..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0host.py"
) else (
  python "%~dp0host.py"
)
