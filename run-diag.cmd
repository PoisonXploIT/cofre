@echo off
rem Modo diagnostico: abre el cofre con la consola visible para leer los errores.
rem El acceso directo normal usa pythonw.exe y no muestra nada si falla.
setlocal
cd /d "%~dp0"
echo ============================================
echo  COFRE - modo diagnostico
echo ============================================
echo Carpeta: %CD%
echo.
call run.cmd gui
echo.
echo --------------------------------------------
echo El cofre se ha cerrado con codigo %ERRORLEVEL%.
echo Si arriba no hay ningun mensaje de error, el cierre fue normal.
echo Pulsa una tecla para cerrar esta ventana.
pause >nul
endlocal
