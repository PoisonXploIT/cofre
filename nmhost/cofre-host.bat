@echo off
rem COFRE - host de mensajeria nativa. El navegador lo lanza por cada mensaje.
rem No abre el cofre: reenvia a la tuberia donde escucha la GUI.
cd /d "%~dp0.."
"C:\Users\Sammi\AppData\Local\Programs\Python\Python312\python.exe" -u -m cofre.nmhost
