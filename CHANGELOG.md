# COFRE — registro de cambios

La versión vive en `cofre/__init__.py` (`run.cmd --version`).

## 1.0.0 — 2026-11-20

Primera versión completa: bóveda local de secretos con llave física, navegador,
git, ciclo de vida de credenciales y registro firmado. Lo que había antes de esta
línea (rama `master`): cofre local con llave en pendrive, un solo formato, sin
navegador ni log firmado.

### Formato v2 y llaves

- Contenedor cifrado con **una ranura por pendrive** y llave de 32 bytes distinta en
  cada uno (D11). Una copia del pendrive es otra llave física.
- **PIN en el pendrive** (D22): la llave pasa a ser posesión + conocimiento. La ranura
  guarda solo `pin: true`; la frase no se escribe en ningún sitio. `stick-pin` crea la
  ranura nueva, la verifica releyendo (llave+PIN abre, llave sola no) y solo entonces
  quita la vieja; si algo falla, restaura el fichero.
- **Código de recuperación** de 24 palabras más una de control (25) para abrir sin
  pendrive. Solo en papel; no se guarda en ningún fichero.
- Índice cifrado con los **dominios asignados dentro** (D10), tipos, etiquetas,
  política, salud, caducidad, consumidores y el diario de rotación.
- Migración real desde v1 con código de recuperación, histórico v1 en solo lectura y
  anclado por hash.
- Los datos salen del repo: `%LOCALAPPDATA%\cofre\vault`, con `COFRE_VAULT`.

### Sesión y políticas

- Sesión con inactividad (10 min), máximo (8 h), suspensión y bloqueo de Windows.
- Bloqueo automático al retirar el pendrive con el que se abrió.
- Política por secreto y canal: **browser, exec, clipboard, reveal y git**.
- Confirmación en pantalla: Denegar por defecto, 20 s, "Permitir una vez" y
  "Permitir 5 minutos" (por host en git), con retardo de 700 ms para que un clic
  heredado no autorice nada.
- Pantalla de bloqueo con las llaves, el campo PIN cuando el gate lo pide, y avisos
  que dicen la causa real (falta la frase / el PIN no abre / el pendrive no está).

### Auditoría

- Log encadenado con **HMAC** y **checkpoint** que se sella en cada evento.
- Eventos privilegiados sin firma = manipulación; re-anclar solo a mano, con motivo.
- Los rekeys no re-firman el pasado: cierran el tramo con la clave vieja, lo archivan
  en solo lectura y el nuevo lo ancla por SHA-256.
- Reglas de alerta (ráfaga, señuelo, fallos, hora rara, puente, log) con enfriamiento.

### Navegador y git

- Mensajería nativa + **tubería con nombre**, con validación de cliente (binario,
  usuario, PID) y sin puertos abiertos. TCP 47653 solo como respaldo del navegador.
- Relleno solo en los dominios asignados a **ese** secreto. Señuelos que nunca se
  entregan.
- Aviso del navegador: "Para este sitio" primero, **Asignar** con confirmación en la
  GUI, **Guardar este sitio en COFRE**, **generar contraseña y guardarla** en una web
  de registro, insignia `off`, atajo Ctrl+Shift+L.
- **Ayudante de git**: no abre el cofre; pide por la tubería, canal `git`,
  confirmación por host con 5 minutos y log `git:<host> pid=...`. Con la GUI cerrada
  no devuelve nada.
- Permisos temporales **a la vista**: `git: github.com permitido 4:12` con botón
  Retirar y evento firmado `grant-revoke`.

### Ciclo de vida de credenciales

- Proveedores Cloudflare y GitHub; **proveedor genérico** configurable (catálogo
  verificado contra la API real: Tavily, OpenAI, Hugging Face, Anthropic, Stripe) y
  `meta --verify` para cualquier otra API.
- Rotación con diario cifrado dentro del índice, historial de 5 versiones, credencial
  vieja anotada, aviso a los 7 días y `resume` para deshacer o continuar.
- **Salud** con verificación real, calendario sin nombres (`cofre-schedule.json`) y
  `due --notify`.
- **Pánico** (`panic`, con `--dry-run`) y `rekey` de la clave maestra.

### Uso desde línea de comandos

- `run` con `.cofre-env.json` (`cofre://NOMBRE`, `#campo`, `@app`) y `--check`.
- `describe` (completo local) y `describe --minimal` para agentes.
- `add --from-file` para valores multilínea (el `.pem` de la GitHub App).
- `--recovery` en cualquier comando de lectura: abrir con el papel.
- `scan` (**escáner de fugas**): compara huellas HMAC de tus secretos con lo que hay
  en tus proyectos, sin mostrar el valor, y gancho de `pre-commit` que para el commit
  con fuga.
- `sesion`: comprueba lo que se puede sin el usuario (discos, registro, `log verify`,
  reserva, recordatorio, plan de pánico y copia con simulacro de restauración). Con
  `--gate usb-pin` pide la frase **una vez** con `getpass` y se la pasa a cada paso
  solo en el entorno del hijo; con `COFRE_AGENT=1` no la pide y sale con código 3.
- `version` y `--version`.

### Interfaz

- Tres columnas, paleta Ctrl+K, Llaves y recuperación, Ajustes, primer uso guiado,
  teclado y foco, pantalla de bloqueo que no titila.
- Catálogo de mensajes `cofre/messages.py` con **trinquete** de textos: GUI 263, CLI
  355; subir exige `--justificar "motivo"` y queda anotado con fecha.
- Todo lo que pinta ocurre en el hilo de Tkinter (`assert_main`); la tubería atiende
  una conexión por hilo y el único que espera es quien pide.

### Pruebas y comprobaciones

- **391 pruebas** y **24 sondas obligatorias** (`tools/run_all_probes.py`), más
  `tools/check_all.py` para el cierre (pruebas, selftest, layout, tema, log sobre
  cofre temporal y escaneo del repo).
- Sondas de hardware/navegador marcadas como opcionales.

### Arreglos de la última pasada (2026-11-20)

- La ventana no abría con `--gate usb-pin` aunque el PIN fuese bueno: `_bind_material`
  no le pasaba el PIN a `material_for`.
- El PIN tecleado en la pantalla de bloqueo no llegaba a la app (`app.pin_field` no
  existía): `Abrir` y `Reconectar` iban con PIN vacío. Ahora `Abrir`, `Reconectar` y
  Enter en el campo leen ese campo.
- Avisos honestos: sin frase, "falta la frase del cofre"; con frase incorrecta, "la
  frase no abre este pendrive". Ya no se culpa al pendrive cuando está puesto.
- `gui --selftest` informa del estado en vez de petar con `SlotError` si la ranura
  pide frase.
- La tubería y `nmhost` aceptan el intérprete base de un venv (`pyvenv.cfg`) al
  comparar ejecutables: antes rechazaban al propio python del proyecto.
- `backup_restore_probe --gate usb-pin` valida copias con PIN, no se queda esperando
  en `getpass` y, si falta la frase, sale con código 2 en vez de decir "la copia NO
  abre".
- La ventana de bloqueo pide el PIN antes de los botones y el marco mide lo que mide
  su contenido.

## 0.9.0 — 2026-11-18

Fase 8 cerrada salvo 8.5 (PyInstaller, descartado por D17). 223 pruebas.

## Cómo se comprueba

```
cd C:\Users\Sammi\AI\cofre
.\run.cmd --version
py -3 tools\check_all.py            (o .venv\Scripts\python.exe tools\check_all.py)
py -3 tools\run_all_probes.py
.\run.cmd --gate usb-pin sesion     (con E: y F: puestos; pide la frase una vez)
```
