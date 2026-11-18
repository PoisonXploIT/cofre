@echo off
rem Arranca el cofre. Se puede llamar desde cualquier directorio: primero se
rem coloca en la carpeta del propio script, porque el venv vive aqui.
rem Los DATOS (cofre.json, sal, pendrives, registro) ya NO estan en el repo:
rem viven en %LOCALAPPDATA%\cofre\vault y se localizan con COFRE_VAULT.
setlocal
pushd "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo No existe el entorno .venv; creandolo...
    python -m venv .venv
    .venv\Scripts\python -m pip install -q cryptography fido2 pynacl
)

.venv\Scripts\python -m cofre.cli %*
set "RC=%ERRORLEVEL%"

popd
endlocal & exit /b %RC%
