@echo off
rem Arranca el cofre. Se puede llamar desde cualquier directorio: primero se
rem coloca en la carpeta del propio script, porque el venv y los datos
rem (cofre.json, .cofre-salt, .cofre-sticks.json) viven aqui.
setlocal
pushd "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo No existe el entorno .venv; creandolo...
    python -m venv .venv
    .venv\Scripts\python -m pip install -q cryptography fido2
)

.venv\Scripts\python -m cofre.cli %*
set "RC=%ERRORLEVEL%"

popd
endlocal & exit /b %RC%
