@echo off
rem COFRE - host de mensajeria nativa. El navegador lo lanza por cada mensaje.
rem No abre el cofre: reenvia a la tuberia donde escucha la GUI.
rem Busca un interprete sin rutas fijas: primero el venv del repo, luego python del PATH.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -u -m cofre.nmhost
) else (
  python -u -m cofre.nmhost
)
