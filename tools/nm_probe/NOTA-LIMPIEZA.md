# Limpieza de la sonda H23 (2026-11-16)

Hecho por el agente:

- 12 claves HKCU borradas (Google\Chrome, BraveSoftware\Brave-Browser, Chromium).
- 6 claves que quedaron de las pruebas de rutas: Software\Brave, Software\Brave-Browser,
  BraveSoftware\Brave, BraveSoftware\Brave-Browser\Application, Chrome Beta, Chrome SxS.
- Contenedores vacios borrados. La raiz Software\Google\Chrome\NativeMessagingHosts se
  deja porque contiene hosts de Microsoft (browsercore, onedrive).
- %LOCALAPPDATA%\cofre-nm borrado.
- Comprobado: ninguna clave con "cofre" en HKCU ni HKLM.

Pendiente (lo tiene que hacer el usuario, requiere Brave abierto):

brave://extensions -> "COFRE NM probe (sonda H23)" -> Quitar.
