---
created: 2026-11-13
modified: 2026-11-13
tags: [cofre, plan, seguridad, ux, ui, rotacion, navegador, roadmap]
aliases: [COFRE plan profesional, COFRE plan PRO]
---

# COFRE - plan de mejora a herramienta profesional (2026-11-13)

Contexto previo: [[COFRE]], [[COFRE-ARQUITECTURA]], [[COFRE-INTEGRACION-2026-11-13]],
[[COFRE-PLAN-UX-2026-11-10]], [[COFRE-PLAN-ESTETICA-2026-11-10]], [[COFRE-USO-SECRETOS]].

Este plan lo va a ejecutar un **LLM local pequeño**. Por eso está escrito con
mucho detalle, con pasos cortos, código guía y pruebas concretas. Si eres ese
LLM: lee primero la sección 0 entera, sin saltarte nada.

---

## Índice

0. Instrucciones para el LLM que ejecuta este plan (OBLIGATORIO)
1. Qué es COFRE hoy (verificado leyendo el código el 2026-11-13)
2. Qué significa "profesional" aquí: definición de terminado
3. Modelo de amenazas: "incluso si me hackean"
4. Reglas inquebrantables
5. Hallazgos de la revisión (bugs y riesgos, con prioridad)
6. Mapa de fases y orden
7. Fase 0 - Cimientos y red de seguridad
8. Fase 1 - Formato de cofre v2 (núcleo criptográfico)
9. Fase 2 - Sesión, bloqueo y políticas por secreto
10. Fase 3 - Auditoría a prueba de manipulación y detección de intrusos
11. Fase 4 - Navegador profesional
12. Fase 5 - Ciclo de vida y rotación de credenciales (Cloudflare, GitHub, genéricos)
13. Fase 6 - UX/UI profesional
14. Fase 7 - Integración con todo (terminal, git, proyectos, harness)
15. Fase 8 - Calidad, recuperación y documentación
16. Fase 9 (opcional) - Llave FIDO2 por la API WebAuthn de Windows
17. Lo que NO se va a hacer
18. Decisiones abiertas para el usuario
19. Apéndices: plantillas, glosario, referencias de API

---

## 0. Instrucciones para el LLM que ejecuta este plan (OBLIGATORIO)

### 0.1 Dónde está cada cosa

| Qué | Ruta |
|---|---|
| Código (repo git) | `C:\Users\Sammi\AI\cofre\` |
| Paquete Python | `C:\Users\Sammi\AI\cofre\cofre\` |
| Extensión Chrome | `C:\Users\Sammi\AI\cofre\extension\` |
| Herramientas y sondas | `C:\Users\Sammi\AI\cofre\tools\` |
| Documentación (este plan y el resto) | `C:\Users\Sammi\Documents\Destino\40-IA\PROYECTOS\COFRE\` |
| Cofre REAL del usuario | `%USERPROFILE%\AI\cofre\cofre.json` (NO TOCAR) |
| Llaves REALES | `E:\COFRE.KEY` y `F:\COFRE.KEY` (NO TOCAR) |

Regla de la casa ya existente: **el código va al repo; la documentación va a la
carpeta de documentación.** No mezclar.

### 0.2 Cómo trabajar, paso a paso

1. Trabaja **un solo paso cada vez**, en el orden del plan. No adelantes pasos.
2. Antes de empezar un paso, lee su bloque completo: Objetivo, Archivos,
   Instrucciones, Prueba y "Hecho cuando".
3. Abre **solo** los archivos que el paso indica. Si un archivo tiene más de 300
   líneas, busca la función con `findstr /n "def nombre" archivo.py` (o `grep -n`)
   y lee solo esa zona (unas 80 líneas alrededor).
4. Haz el cambio mínimo que pide el paso. **No** reformatees, no renombres cosas
   que el paso no menciona, no "mejores" código de paso.
5. Ejecuta la prueba del paso **y** la batería completa:
   ```
   cd C:\Users\Sammi\AI\cofre
   python -m unittest discover -s tests -v
   python -m cofre.cli gui --selftest
   ```
   (La batería existe desde el paso 0.2. Antes de eso, solo la prueba del paso.)
6. Si todo pasa: un commit por paso con el formato del apéndice 19.2.
7. Apunta el resultado en `PLAN-PRO-PROGRESO.md` (carpeta de documentación) con
   la plantilla del apéndice 19.3.
8. Si algo falla dos veces seguidas: **para**. Escribe en `PLAN-PRO-PROGRESO.md`,
   sección `## BLOQUEOS`, qué intentaste, qué error salió (copia literal) y qué
   crees que pasa. No sigas al paso siguiente.

### 0.3 Cuándo parar y preguntar al usuario

Para y pregunta (sección `## PREGUNTAS` de `PLAN-PRO-PROGRESO.md`) si:

- un paso te obligaría a tocar el cofre real, `E:\` o `F:\`;
- necesitas instalar un paquete que no está en la lista del apéndice 19.5;
- una API externa responde distinto de lo que dice el apéndice 19.6;
- un paso marcado **[DECISIÓN]** no tiene la decisión tomada en la sección 18;
- dudas entre dos interpretaciones de un paso.

**No inventes** endpoints, nombres de funciones de librerías ni opciones de
línea de comandos. Si no está en este plan o en la documentación oficial,
pregunta.

### 0.4 Cómo probar sin tocar nada real

Toda prueba usa un cofre temporal y un "pendrive falso" (una carpeta con un
fichero `COFRE.KEY`). El helper del paso 0.2 lo crea. En terminal:

```
set COFRE_VAULT=%TEMP%\cofre-prueba\cofre.json
python -m cofre.cli --stick %TEMP%\cofre-prueba\stick\COFRE.KEY list
```

Valores de prueba: usa cadenas evidentes como `valor-de-prueba-123`. **Nunca**
copies un secreto real a un test, a un log o a un mensaje de commit.

### 0.5 Estilo de código

- Python 3.11+ (comprobar con `python --version`; si es menor, avisar).
- Solo librería estándar + las dependencias del apéndice 19.5.
- Comentarios y mensajes al usuario **en español**, sin tecnicismos en la GUI.
- Funciones cortas (menos de 50 líneas). Archivos nuevos: menos de 400 líneas.
- Toda escritura a disco de ficheros del cofre pasa por `cofre/fsutil.py`
  (paso 0.4).
- Nunca `print()` de un valor secreto, salvo en `get`/`export` del CLI, que ya
  están protegidos.

---

## 1. Qué es COFRE hoy (verificado leyendo el código el 2026-11-13)

**Funciona:**

- Cifrado AES-256-GCM por secreto bajo una clave maestra K (`crypto.py`).
- K va envuelta con una clave de sesión S = scrypt(32 bytes de `COFRE.KEY` + PIN
  opcional, sal de `.cofre-salt`) (`usb.py`, `gate.py`).
- Dos pendrives (E: principal, F: reserva) con **la misma** clave copiada.
- Lista de seriales autorizados en `.cofre-sticks.json` (texto plano).
- CLI: init, add, get, list, del, exec, check, gen, export, log, stick-*.
- GUI Tkinter (`gui.py`, ~900 líneas): abrir, bloquear, ver 15 s, copiar con
  limpieza a 30 s, renombrar, editar, tags, generador, asistente de arranque,
  auto-bloqueo al quitar el pendrive, guía paginada.
- Puente al navegador: servidor en `127.0.0.1:47653` que solo acepta el
  `Origin` de la extensión; extensión MV3 que lista nombres y rellena.
- Log de accesos `.cofre-access.log` (texto plano, sin valores).

**No existe todavía:** rotación de claves, caducidades, metadatos de proveedor,
vinculación secreto↔dominio, historial de versiones, copias de seguridad
automáticas, código de recuperación en papel, detección de manipulación,
alertas, pruebas automáticas, integración con git/proyectos.

---

## 2. Qué significa "profesional" aquí: definición de terminado

COFRE se considera profesional cuando se cumplen **todas** estas frases, y cada
una se puede comprobar con una prueba:

1. Perder **un** pendrive no hace perder el cofre, y ese pendrive se puede dar de
   baja **criptográficamente** (no solo en una lista).
2. Perder **los dos** pendrives no hace perder el cofre (código de recuperación
   en papel).
3. Copiar `cofre.json` no revela **ni los nombres** de los secretos.
4. Manipular `cofre.json`, el registro de pendrives o el log se **detecta**.
5. Un secreto solo se rellena en el navegador en los **dominios** que tiene
   asignados. En una web de phishing, no se rellena.
6. Cada credencial de proveedor sabe: de qué proveedor es, qué permisos tiene,
   cuándo caduca, cuándo se rotó, dónde está desplegada.
7. Las credenciales de Cloudflare se rotan **solas** (con confirmación); las de
   GitHub se rotan de forma **asistida** o se sustituyen por tokens de 1 hora.
8. Existe un **botón de pánico** que revoca o rota todo lo revocable.
9. Hay alertas cuando pasa algo raro (muchas lecturas, lectura de un señuelo,
   fallos de apertura).
10. La interfaz se entiende sin leer la guía: crear, buscar, usar y rotar un
    secreto se hace en menos de 4 clics o con el teclado.
11. Hay batería de pruebas automática y pasa entera.

---

## 3. Modelo de amenazas: "incluso si me hackean"

Hay que decirlo sin adornos: **ningún gestor de secretos protege un secreto que
se está usando en un equipo con malware.** Si un atacante controla tu sesión de
Windows mientras el cofre está abierto, puede leer lo que el cofre descifra.
Lo que sí se puede conseguir, y es lo que este plan persigue:

| Capa | Objetivo | Cómo |
|---|---|---|
| 1. Reducir lo expuesto | Que en cada momento haya lo mínimo descifrado | Bloqueo por inactividad, por quitar el pendrive, por bloquear Windows; nada en disco en claro |
| 2. Reducir el daño | Que una clave robada sirva para poco y poco tiempo | Tokens con permisos mínimos, un token por uso, caducidad corta, restricción por IP, tokens de 1 hora (GitHub App) |
| 3. Detectar | Saber que te han atacado | Log encadenado con HMAC, alertas, credenciales señuelo (honeytokens), escáner de fugas |
| 4. Reaccionar rápido | Invalidar todo en minutos | Rotación automática, botón de pánico, inventario de dónde está cada clave |
| 5. Recuperarse | No perder el acceso | Llave propia por pendrive, código de recuperación, copias cifradas |

### 3.1 Adversarios y qué consigue cada uno tras este plan

| Adversario | Hoy | Tras el plan |
|---|---|---|
| Roba `cofre.json` (backup, nube, disco) | Ve los **nombres** y tags de todos los secretos | No ve nada: índice cifrado |
| Roba `cofre.json` + un pendrive viejo revocado | Abre el cofre (misma clave en ambos) | No abre el cofre actual (el slot se borró y se hizo `rekey`) |
| Edita `.cofre-sticks.json` para autorizar su USB | Lo consigue (texto plano sin firma) | Detectado: los seriales viven dentro del cofre, autenticados |
| Web de phishing que imita Cloudflare | La extensión rellena si el usuario pulsa | No rellena: dominio no autorizado |
| Malware local llama al puerto 47653 | Basta con falsificar `Origin` | Necesita el token de emparejamiento; las entradas sensibles piden confirmación en pantalla |
| Malware con la sesión abierta | Lee todo lo descifrado | Sigue pudiendo leer lo que se descifra **en ese momento**; queda en el log, salta alerta, y la rotación limita la vida útil |
| Keylogger | Captura el PIN | Igual; por eso el PIN es segundo factor, no el único |

### 3.2 Principios que se derivan

1. **Un token por consumidor.** Nunca la misma clave de Cloudflare en tres sitios:
   tres tokens. Así revocar uno no rompe los otros y se sabe cuál se filtró.
2. **Permisos mínimos y caducidad siempre.** Si el proveedor lo permite, el token
   caduca y está limitado por IP.
3. **Preferir credenciales de vida corta** a credenciales de larga vida rotadas.
4. **La clave "maestra" de un proveedor** (la que puede crear y borrar tokens) es
   el secreto más sensible: política `confirmar siempre`, nunca va a `exec` ni al
   navegador.
5. **Honestidad en la interfaz:** la GUI nunca dice "seguro" sin matices.

---

## 4. Reglas inquebrantables

El LLM ejecutor **nunca**:

1. Abre en escritura el cofre real, `E:\COFRE.KEY` o `F:\COFRE.KEY`.
2. Ejecuta `stick-init --force`, `stick-revoke` o `migrate` sobre el cofre real.
   Esos comandos los ejecuta **el usuario**, cuando el plan lo indique.
3. Escribe un valor secreto en un fichero en claro, en una línea de comandos, en
   el log, en un mensaje de error o en un commit.
4. Añade un "recordarme" que guarde la clave de sesión en disco.
5. Exporta secretos a `HKCU\Environment` o a ficheros `.env` (ver sección 17).
6. Abre el puente del navegador a algo que no sea `127.0.0.1`.
7. Desactiva una comprobación de seguridad "para que pase la prueba".
8. Borra el código v1 de lectura antes de que la migración a v2 esté verificada
   por el usuario con su cofre real.

---

## 5. Hallazgos de la revisión (bugs y riesgos, con prioridad)

P1 = arreglar ya (Fase 0). P2 = lo resuelve una fase posterior. Las líneas son
aproximadas: localiza siempre por nombre de función.

| # | Prio | Archivo / función | Problema | Se resuelve en |
|---|---|---|---|---|
| H1 | P1 | `cli.py` comando `exec` | `except VaultError:` usa un nombre que no existe. Si falta un secreto, el programa revienta con `NameError` en vez de decir "no encontrados" | 0.4 |
| H2 | P1 | `gui.py` `build()` | `self.browser_btn` se crea dos veces (cabecera y pie). La referencia queda en el del pie y el de la cabecera nunca cambia a "on" | 0.4 |
| H3 | P1 | `gui.py` `build()` | `Ctrl+C` está atado a toda la ventana y copia **el valor del secreto** aunque estés copiando texto del buscador. Riesgo de pegar un secreto donde no toca | 0.4 |
| H4 | P1 | `gui.py` `build()` | `Escape` cierra la aplicación entera. Un toque accidental cierra el cofre | 0.4 |
| H5 | P1 | `gate.py` modo `pin` | Duplica la lógica de `_salt_for` en vez de llamarla | 0.4 |
| H6 | P1 | `serve.py` `main()` | Ignora `--gate` y `--stick`: siempre usa `usb` | 0.4 |
| H7 | P1 | `usb.py` `save_registry`, `audit.py`, `gate.py` `_salt_for` | Escrituras no atómicas: un corte de luz a mitad deja el fichero corrupto | 0.4 |
| H8 | P1 | Cinco archivos | La ruta por defecto del cofre está copiada en `cli.py`, `serve.py`, `gui.py`, `usb.py`, `audit.py` | 0.3 |
| H9 | P1 | `.cofre-salt` | Si se pierde la sal (fichero suelto junto al cofre), el cofre **no se abre nunca más**, aunque tengas el pendrive. Una copia de seguridad de `cofre.json` sin la sal no sirve | 1.x (la sal pasa dentro del cofre) |
| H10 | P2 | `crypto.py` | Nombres y tags de los secretos en texto plano dentro de `cofre.json` | 1.4 |
| H11 | P2 | `crypto.py` | El blob cifrado no está atado a su nombre (sin AAD): se pueden intercambiar blobs entre entradas sin que se detecte | 1.2 |
| H12 | P2 | `usb.py` | Los dos pendrives tienen la misma clave: "revocar" uno solo lo quita de una lista editable; quien tenga el pendrive y edite la lista sigue entrando | 1.3 |
| H13 | P2 | `usb.py` `find_stick` | Con el registro vacío autoriza **todos** los volúmenes con `COFRE.KEY` que encuentre | 1.3 |
| H14 | P2 | `crypto.py` `add` | Sobrescribir un secreto pierde el valor anterior sin historial ni deshacer | 1.5 |
| H15 | P2 | `audit.py` | Log en texto plano, sin encadenar: se puede borrar o editar sin rastro | 3.1 |
| H16 | P2 | `extension/manifest.json` | `content_scripts` en **todas** las webs (`http://*/*`, `https://*/*`) | 4.1 |
| H17 | P2 | `content.js` `pickFields` | Rellena el campo enfocado de cualquier web, sin comprobar el dominio: phishing | 4.2 |
| H18 | P2 | `popup.js` `fill` | El valor del secreto pasa por el popup (más superficie) | 4.3 |
| H19 | P2 | `serve.py` | La única barrera contra programas locales es la cabecera `Origin`, que se falsifica trivialmente | 4.4 |
| H20 | P2 | `gui.py` | Un único archivo de ~900 líneas: inmanejable para un LLM pequeño | 0.5 |
| H21 | P2 | Todo | Cero pruebas automáticas en `tests/` | 0.2 |
| H22 | Info | `cofre.json` en el Proyecto de claude.ai | Hay una copia del envoltorio del cofre subida al Proyecto. Sin `COFRE.KEY` no se abre, pero es mejor no subir copias del cofre a servicios en la nube. El usuario debería quitarla del Proyecto | Usuario |
| H23 | Info | `gate.py`, `COFRE-INTEGRACION` | La decisión "Chrome no puede lanzar un `.cmd` como host de mensajería nativa" no está verificada. La documentación de Chrome y de Mozilla usa un `.bat` como envoltorio en Windows. Merece una sonda antes de descartarlo | 4.0 |
| H24 | Info | `gate.py` llave FIDO2 | El `ERROR_ACCESS_DENIED` al abrir el HID FIDO es el comportamiento normal de Windows 10/11 para programas sin privilegios: hay que pasar por la API WebAuthn de Windows (`webauthn.dll`), no por HID directo. La llave podría servir por esa vía | 16 (opcional) |

---

## 6. Mapa de fases y orden

```
F0 Cimientos ──► F1 Formato v2 ──► F2 Sesión ──► F3 Auditoría ──► F4 Navegador
                                       │                              │
                                       └──────────► F5 Rotación ◄─────┘
F0 ──► F6 UX/UI (6.1 puede ir justo después de F0; el resto tras F2)
F5 + F6 ──► F7 Integraciones ──► F8 Calidad y recuperación ──► F9 (opcional)
```

Hitos (cada uno deja COFRE usable y mejor que antes):

| Hito | Fases | Qué gana el usuario |
|---|---|---|
| M1 | F0 | Sin bugs conocidos, con pruebas, GUI dividida |
| M2 | F1 + F2 | Cofre v2: nada visible sin pendrive, recuperación en papel, bloqueo automático |
| M3 | F3 | Sabe si alguien ha tocado el cofre; alertas; señuelos |
| M4 | F4 | Relleno seguro en el navegador, a prueba de phishing |
| M5 | F5 | Rotación de Cloudflare/GitHub, caducidades, pánico |
| M6 | F6 | Interfaz profesional |
| M7 | F7 + F8 | Integrado con terminal, git y proyectos; recuperación ensayada |

---

## 7. Fase 0 - Cimientos y red de seguridad

### Paso 0.1 - Rama de trabajo y fichero de progreso

- **Objetivo:** trabajar sin riesgo sobre una rama aparte.
- **Archivos:** ninguno de código. Crear `PLAN-PRO-PROGRESO.md` en la carpeta de
  documentación.
- **Instrucciones:**
  1. `cd C:\Users\Sammi\AI\cofre` y `git status`. Si hay cambios sin commit,
     **para** y pregunta al usuario.
  2. `git checkout -b pro`.
  3. Abre `.gitignore` y comprueba que contiene estas líneas; añade las que
     falten:
     ```
     cofre.json
     *.json.bak*
     .cofre-*
     *.KEY
     *.pem
     backups/
     __pycache__/
     .venv/
     ```
  4. Crea `PLAN-PRO-PROGRESO.md` con las secciones `## REGISTRO`,
     `## BLOQUEOS`, `## PREGUNTAS`.
- **Hecho cuando:** `git branch` muestra `* pro`; el fichero de progreso existe.
- **Commit:** `chore: rama pro y gitignore ampliado`

### Paso 0.2 - Batería de pruebas con `unittest`

- **Objetivo:** que cada paso posterior se pueda verificar solo.
- **Por qué `unittest`:** viene con Python; no hay que instalar nada.
- **Archivos a crear:** `tests/__init__.py` (vacío), `tests/helpers.py`,
  `tests/test_crypto_v1.py`, `tests/test_cli_v1.py`.
- **Código guía `tests/helpers.py`:**
  ```python
  """Utilidades de prueba: cofre temporal y pendrive falso.
  Nunca tocan el cofre real ni E:/F:."""
  import os, secrets, shutil, tempfile
  from pathlib import Path

  class TempVault:
      def __init__(self):
          self.root = Path(tempfile.mkdtemp(prefix="cofre-test-"))
          self.vault = self.root / "cofre.json"
          self.stick_dir = self.root / "stick"
          self.stick_dir.mkdir()
          self.key = self.stick_dir / "COFRE.KEY"
          self.key.write_bytes(secrets.token_bytes(32))
          self._old_env = os.environ.get("COFRE_VAULT")
          os.environ["COFRE_VAULT"] = str(self.vault)

      def close(self):
          if self._old_env is None:
              os.environ.pop("COFRE_VAULT", None)
          else:
              os.environ["COFRE_VAULT"] = self._old_env
          shutil.rmtree(self.root, ignore_errors=True)
  ```
- **Pruebas mínimas a escribir** (cada una en un método `test_...`):
  - `crypto`: init + add + get devuelve el mismo valor; get con otra sesión
    lanza excepción; delete borra; rename conserva el valor.
  - `cli`: `main(["--vault", v, "--stick", k, "init"])` devuelve 0; `add NOMBRE
    valor` devuelve 0; `check --name NOMBRE` devuelve 0; `check --name NOEXISTE`
    devuelve 1.
  - Para el CLI, llama a `cofre.cli.main([...])` directamente, no con
    `subprocess`.
- **Prueba:** `python -m unittest discover -s tests -v` → todas `ok`.
- **Hecho cuando:** al menos 8 pruebas pasan.
- **Commit:** `test: bateria minima de pruebas v1`

### Paso 0.3 - Configuración centralizada

- **Objetivo:** una sola fuente para rutas, puertos y tiempos.
- **Archivos:** crear `cofre/config.py`; modificar `cli.py`, `serve.py`,
  `gui.py`, `usb.py`, `audit.py` (solo las líneas de la ruta por defecto).
- **Código guía:**
  ```python
  """COFRE - configuracion. Nada secreto vive aqui."""
  import json, os
  from pathlib import Path

  BRIDGE_PORT = 47653
  REVEAL_SECONDS = 15
  CLIPBOARD_SECONDS = 30
  IDLE_LOCK_MINUTES = 10        # se usa desde la Fase 2
  MAX_SESSION_HOURS = 8         # se usa desde la Fase 2

  def default_vault_path() -> Path:
      env = os.environ.get("COFRE_VAULT")
      if env:
          return Path(env)
      return Path.home() / "AI" / "cofre" / "cofre.json"

  def settings_path(vault_path) -> Path:
      return Path(vault_path).parent / "cofre-settings.json"

  def load_settings(vault_path) -> dict:
      """Ajustes NO secretos del usuario (tiempos, idioma). Si falta o esta
      roto, se devuelven los valores por defecto."""
      defaults = {"reveal_seconds": REVEAL_SECONDS,
                  "clipboard_seconds": CLIPBOARD_SECONDS,
                  "idle_lock_minutes": IDLE_LOCK_MINUTES,
                  "max_session_hours": MAX_SESSION_HOURS}
      p = settings_path(vault_path)
      try:
          data = json.loads(p.read_text(encoding="utf-8"))
          defaults.update({k: data[k] for k in defaults if k in data})
      except (OSError, ValueError):
          pass
      return defaults
  ```
- **Instrucciones:** en cada uno de los cinco archivos, sustituye la expresión
  `Path(os.environ.get("COFRE_VAULT", Path.home() / "AI" / "cofre" / "cofre.json"))`
  (o su variante con `str(...)`) por `default_vault_path()` (o
  `str(default_vault_path())`). No cambies nada más.
- **Prueba:** `findstr /s /n "AI\" \"cofre\" \"cofre.json" cofre\*.py` solo
  encuentra `config.py`. Batería completa en verde.
- **Commit:** `refactor: ruta del cofre centralizada en config.py`

### Paso 0.4 - Corregir los bugs P1 (H1-H7)

Haz **un commit por bug**, cada uno con su prueba si es posible.

**0.4.a (H1) `exec` con secreto inexistente.** En `cli.py`, dentro del bloque
`if args.command == "exec":`, cambia `except VaultError:` por `except KeyError:`.
Prueba nueva: `main([... "exec", "--name", "NOEXISTE", "--", "python", "-c", "pass"])`
devuelve 1 y no lanza excepción.

**0.4.b (H2) botón Navegador duplicado.** En `gui.py` `build()`, borra las dos
líneas que crean `self.browser_btn` **en la cabecera** (`top`). Se queda solo el
del pie. Prueba: `gui --selftest` sin error.

**0.4.c (H3) Ctrl+C.** Cambia la línea
`self.root.bind("<Control-c>", lambda _e: self.copy_to_clipboard())` por un
manejador que **solo copia el secreto si el foco no está en un campo de texto**:
```python
def _ctrl_c(self, event=None):
    w = self.root.focus_get()
    if isinstance(w, (tk.Entry, tk.Text)):
        return None          # deja que Tk copie el texto seleccionado
    self.copy_to_clipboard()
    return "break"
```
y `self.root.bind("<Control-c>", self._ctrl_c)`.

**0.4.d (H4) Escape.** Cambia `self.root.bind("<Escape>", lambda _e: self._on_close())`
por `self.root.bind("<Escape>", lambda _e: self.hide())` (Escape oculta el valor
visible; cerrar es con la X o `Ctrl+Q`). Añade
`self.root.bind("<Control-q>", lambda _e: self._on_close())`. Actualiza el texto
de ayuda donde se mencionen los atajos.

**0.4.e (H5) sal duplicada.** En `gate.py`, en el modo `pin` de
`resolve_session_key`, sustituye el bloque que lee/crea `.cofre-salt` por
`salt = _salt_for(vault_path)`.

**0.4.f (H6) `serve.main`.** Añade lectura de `--gate` (por defecto `usb`) y
`--stick` (por defecto `None`) igual que se lee `--port`, y pásalos a
`SecretServer(vault, origins, gate=gate, stick=stick, port=port)`.

**0.4.g (H7) escrituras atómicas.** Crea `cofre/fsutil.py`:
```python
"""Escritura atomica: o queda el fichero nuevo entero o el viejo entero."""
import os
from pathlib import Path

def atomic_write_bytes(path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)

def atomic_write_text(path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
```
Úsalo en `crypto.Vault.save`, `usb.save_registry`, `gate._salt_for` (al crear
la sal) y en `audit._prune` (al reescribir). En `audit.record` el `append`
puede quedarse como está.

- **Hecho cuando:** 7 commits, batería en verde, `gui --selftest` OK.

### Paso 0.5 - Dividir `gui.py` en un paquete (SIN cambiar comportamiento)

- **Objetivo:** archivos pequeños que un LLM pequeño pueda leer enteros.
- **Regla de oro de este paso:** **mover, no reescribir.** Copia los métodos tal
  cual. Si te tienta "arreglar" algo mientras mueves, apúntalo en PROGRESO y no
  lo hagas.
- **Estructura destino:**
  ```
  cofre/gui/__init__.py      # from .app import main, CofreGUI
  cofre/gui/app.py           # clase CofreGUI: __init__, build (esqueleto), estado, unlock/lock, _poll, main(), parse_args()
  cofre/gui/widgets.py       # funciones _btn y _entry como funciones libres: make_button(gui, parent, ...), make_entry(...)
  cofre/gui/list_view.py     # refresh_list, _kind_of, select, move_selection
  cofre/gui/detail_view.py   # reveal, hide, toggle_sticky, copy_to_clipboard, copy_name, copy_exec_command, edit/rename/delete
  cofre/gui/add_form.py      # add_secret, generate, set_lang, _update_strength, toggle_show_value
  cofre/gui/sticks_view.py   # stick_report, refresh_sticks, revoke_from_gui, revoke_stick_safe, wizard_*
  cofre/gui/bridge_ctl.py    # toggle_browser, start_bridge, stop_bridge
  cofre/gui/guide.py         # GUIDE, open_guide, toggle_help
  ```
- **Técnica recomendada (mixins):** cada módulo define una clase
  `ListViewMixin`, `DetailViewMixin`, etc. con los métodos movidos, y
  `CofreGUI(ListViewMixin, DetailViewMixin, ..., )` las hereda. Así `self.x`
  sigue funcionando sin tocar el cuerpo de los métodos.
- **Instrucciones:**
  1. Crea los módulos vacíos con su clase mixin.
  2. Mueve los métodos de uno en uno. Tras cada módulo: `gui --selftest`.
  3. Deja `cofre/gui.py`? **No**: un paquete `cofre/gui/` y un módulo
     `cofre/gui.py` no pueden convivir. Borra `cofre/gui.py` al final y
     comprueba que `python -m cofre.cli gui --selftest` y
     `python -m cofre.gui --selftest` funcionan (añade `cofre/gui/__main__.py`
     con `from .app import main; raise SystemExit(main())`).
  4. Revisa `run.cmd`, `run-diag.cmd`, `tools/make_shortcut.py` y los `tools/*`
     que importen `cofre.gui`: deben seguir funcionando.
- **Prueba:** `gui --selftest` igual que antes; `python tools/layout_check.py`
  y `python tools/theme_check.py` sin errores nuevos; abrir la GUI a mano y
  probar: abrir, seleccionar, Ver, Copiar, Guardar, Bloquear.
- **Hecho cuando:** ningún archivo de `cofre/gui/` supera 400 líneas.
- **Commit:** `refactor: gui dividida en paquete sin cambios de comportamiento`

---

## 8. Fase 1 - Formato de cofre v2 (núcleo criptográfico)

**Idea general.** Hoy: una clave igual en dos pendrives, sal fuera del fichero,
nombres visibles. v2: el estilo LUKS de "ranuras" (slots). La clave maestra K
se envuelve **una vez por cada llave** (cada pendrive tiene su propia clave
aleatoria, más un código de recuperación en papel). Todo lo demás, incluidos
los nombres, va cifrado.

**Regla:** el código v2 vive en módulos **nuevos**. El v1 se deja intacto para
leer cofres antiguos y migrar.

### Paso 1.1 - Escribir la especificación del formato

- **Archivo a crear:** `docs/FORMATO-V2.md` en la carpeta de documentación, con
  el contenido de esta sección 8 (copia literal del bloque 1.1.a y 1.1.b).

#### 1.1.a Estructura de `cofre.json` v2

```json
{
  "format": 2,
  "vault_id": "uuid4 en texto",
  "created": "2026-11-20T10:00:00",
  "kdf": {"name": "scrypt", "n": 32768, "r": 8, "p": 1},
  "slots": [
    {
      "id": "uuid4",
      "kind": "usb",
      "serial": 3894302289,
      "label": "E: principal",
      "pin": false,
      "salt": "hex 16 bytes",
      "wrap": {"n": "hex 12 bytes", "c": "hex"}
    },
    {
      "id": "uuid4",
      "kind": "recovery",
      "label": "codigo en papel (2026-11-20)",
      "salt": "hex 16 bytes",
      "wrap": {"n": "...", "c": "..."}
    }
  ],
  "index": {"n": "...", "c": "..."},
  "entries": {
    "uuid4-de-la-entrada": {"n": "...", "c": "..."}
  },
  "checkpoint": {"n": "...", "c": "..."}
}
```

#### 1.1.b Derivaciones y AAD (datos autenticados asociados)

| Elemento | Clave | AAD (bytes) |
|---|---|---|
| Envoltorio del slot USB | `scrypt(bytes_de_COFRE.KEY + pin_utf8, salt_slot)` | `b"cofre/v2/slot|" + id + b"|usb|" + str(serial)` |
| Envoltorio del slot recovery | `scrypt(codigo_normalizado_utf8, salt_slot)` | `b"cofre/v2/slot|" + id + b"|recovery|"` |
| Índice | `HKDF(K, info=b"cofre/v2/index")` | `b"cofre/v2/index|" + vault_id` |
| Entrada | `HKDF(K, info=b"cofre/v2/entry")` | `b"cofre/v2/entry|" + vault_id + b"|" + entry_id` |
| Checkpoint del log | `HKDF(K, info=b"cofre/v2/checkpoint")` | `b"cofre/v2/checkpoint|" + vault_id` |
| HMAC del log | `HKDF(K, info=b"cofre/v2/audit")` | (no es cifrado; es HMAC-SHA256) |
| Huellas para detectar fugas | `HKDF(K, info=b"cofre/v2/fingerprint")` | (HMAC-SHA256 del valor) |

Por qué AAD: si alguien mueve el blob de la entrada A a la B, o cambia el serial
de un slot, el descifrado falla con `InvalidTag`. Eso resuelve H11 y H12.

Contenido descifrado del **índice** (JSON):
```json
{
  "entries": {
    "uuid4": {
      "name": "CLOUDFLARE_DNS_TOKEN",
      "type": "api_token",
      "tags": ["cloudflare", "dns"],
      "username": "",
      "urls": ["dash.cloudflare.com"],
      "provider": "cloudflare",
      "provider_ref": {"token_id": "", "account_id": "", "scope": "user"},
      "scopes": "Zone.DNS:Edit en ejemplo.com",
      "created": "2026-11-20T10:00:00",
      "updated": "2026-11-20T10:00:00",
      "expires_at": "2027-02-20",
      "rotate_every_days": 90,
      "last_rotated": "2026-11-20",
      "last_verified": "",
      "consumers": [],
      "policy": {"confirm": false, "browser": true, "exec": true},
      "fingerprint": "hex hmac",
      "notes": ""
    }
  },
  "settings": {}
}
```
Contenido descifrado de una **entrada**:
```json
{"value": "el secreto", "fields": {}, "history": [{"value": "anterior", "replaced": "2026-11-20T10:00:00"}]}
```

Tipos (`type`) permitidos: `password` (web), `api_key`, `api_token` (de
proveedor con id), `oauth_app` (client id + secret), `private_key` (p. ej. clave
de GitHub App), `note` (nota segura), `canary` (señuelo, Fase 3).

### Paso 1.2 - Primitivas criptográficas v2

- **Archivo a crear:** `cofre/v2/__init__.py` (vacío), `cofre/v2/primitives.py`.
- **Código guía (copiar y completar, no cambiar algoritmos):**
  ```python
  """COFRE v2 - primitivas. AES-256-GCM con AAD, HKDF-SHA256, scrypt."""
  import secrets
  from cryptography.hazmat.primitives import hashes
  from cryptography.hazmat.primitives.ciphers.aead import AESGCM
  from cryptography.hazmat.primitives.kdf.hkdf import HKDF
  from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

  def seal(key: bytes, plaintext: bytes, aad: bytes) -> dict:
      nonce = secrets.token_bytes(12)
      return {"n": nonce.hex(), "c": AESGCM(key).encrypt(nonce, plaintext, aad).hex()}

  def unseal(key: bytes, blob: dict, aad: bytes) -> bytes:
      return AESGCM(key).decrypt(bytes.fromhex(blob["n"]), bytes.fromhex(blob["c"]), aad)

  def subkey(master: bytes, label: bytes) -> bytes:
      return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                  info=b"cofre/v2/" + label).derive(master)

  def slot_kek(material: bytes, salt: bytes, kdf: dict) -> bytes:
      """Clave que envuelve a K para un slot (KEK = key encryption key)."""
      return Scrypt(salt=salt, length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(material)

  def aad_slot(slot: dict) -> bytes:
      serial = str(slot.get("serial", "")) if slot["kind"] == "usb" else ""
      return f"cofre/v2/slot|{slot['id']}|{slot['kind']}|{serial}".encode()

  def aad_index(vault_id: str) -> bytes:
      return f"cofre/v2/index|{vault_id}".encode()

  def aad_entry(vault_id: str, entry_id: str) -> bytes:
      return f"cofre/v2/entry|{vault_id}|{entry_id}".encode()
  ```
- **Pruebas** (`tests/test_v2_primitives.py`): `unseal(seal(...))` devuelve lo
  mismo; con otra AAD lanza `cryptography.exceptions.InvalidTag`; con otra clave
  lanza `InvalidTag`; `subkey(K, b"index") != subkey(K, b"entry")`.
- **Commit:** `feat(v2): primitivas con AAD y HKDF`

### Paso 1.3 - Slots: una llave propia por pendrive + código de recuperación

- **Archivo a crear:** `cofre/v2/slots.py`.
- **Funciones a implementar (firmas exactas):**
  ```python
  def new_usb_slot(master: bytes, stick_key: bytes, serial: int, label: str,
                   pin: str, kdf: dict) -> dict: ...
  def new_recovery_slot(master: bytes, code: str, label: str, kdf: dict) -> dict: ...
  def try_open_slot(slot: dict, material: bytes, kdf: dict) -> bytes | None:
      """Devuelve K o None si no abre. Nunca lanza por InvalidTag."""
  def open_with_stick(vault: dict, stick_key: bytes, serial: int, pin: str) -> tuple[bytes, dict]:
      """Prueba SOLO los slots usb con ese serial. Devuelve (K, slot).
      Lanza SlotError('ese pendrive no tiene ranura en este cofre') si no hay."""
  def open_with_recovery(vault: dict, code: str) -> tuple[bytes, dict]: ...
  ```
  - `material` de USB = `stick_key + pin.encode("utf-8")`.
  - `salt` = `secrets.token_bytes(16)` **distinta por slot**.
- **Código de recuperación** (`cofre/v2/recovery.py`):
  - 24 palabras de `wordlist_es.txt` (2000 palabras → ~263 bits) con
    `secrets.choice`.
  - Normalizar antes de derivar: minúsculas, sin tildes
    (`unicodedata.normalize("NFKD", s)` y quitar `Mn`), palabras separadas por un
    espacio, sin espacios extra.
  - Añadir 1 palabra de control: la palabra de índice
    `int(sha256(texto_normalizado).hexdigest(), 16) % 2000`. Así un error al
    teclear se detecta antes de intentar abrir.
- **Por qué cada pendrive con su propia clave:** revocar un pendrive = borrar su
  slot. Ese pendrive deja de abrir el cofre **actual** aunque alguien edite lo
  que quiera. (Ver aviso de `rekey` en el paso 1.6.)
- **Pruebas:** abrir con el pendrive correcto; fallar con otro pendrive; fallar
  con el serial cambiado en el JSON (AAD); abrir con el código de recuperación;
  fallar con una palabra cambiada (detectado por la palabra de control).
- **Commit:** `feat(v2): ranuras por pendrive y codigo de recuperacion`

### Paso 1.4 - Clase `VaultV2` (índice cifrado y entradas)

- **Archivo a crear:** `cofre/v2/vault.py` (< 400 líneas; si crece, separar
  `index.py`).
- **API pública (la misma forma que usará toda la aplicación):**
  ```python
  class VaultV2:
      def __init__(self, path): ...
      @staticmethod
      def create(path, stick_key, serial, label, pin="") -> "VaultV2": ...
      def unlock_with_stick(self, stick_key, serial, pin="") -> None: ...
      def unlock_with_recovery(self, code) -> None: ...
      def lock(self) -> None: ...
      @property
      def is_open(self) -> bool: ...
      # lectura (requieren estar abierto)
      def list(self) -> list[dict]: ...          # metadatos del indice, con "id"
      def find(self, name) -> dict | None: ...   # metadatos por nombre exacto
      def get_value(self, entry_id) -> str: ...
      # escritura
      def put(self, meta: dict, value: str) -> str: ...   # crea; devuelve id
      def update_value(self, entry_id, value) -> None: ...  # guarda historial
      def update_meta(self, entry_id, **changes) -> None: ...
      def delete(self, entry_id) -> None: ...      # va a papelera, ver 1.5
      # llaves
      def add_usb_slot(self, stick_key, serial, label, pin="") -> str: ...
      def add_recovery_slot(self) -> str: ...   # devuelve el codigo UNA vez
      def remove_slot(self, slot_id) -> None: ...  # nunca deja 0 slots
      def slots(self) -> list[dict]: ...           # sin campos 'wrap'
  ```
- **Reglas de implementación:**
  1. El índice se descifra al abrir y se guarda en memoria (`self._index`).
  2. Cada escritura: modificar en memoria → re-cifrar índice (y la entrada
     tocada) → `atomic_write_text` del JSON completo.
  3. Antes de cada escritura, llamar a `backups.rotate(path)` (paso 1.7).
  4. `remove_slot` lanza error si quedaría 0 slots o 0 slots USB.
  5. Los nombres deben ser únicos (comparación sin distinguir mayúsculas).
  6. `fingerprint` = `hmac.new(subkey(K, b"fingerprint"), value.encode(),
     "sha256").hexdigest()`; se recalcula al cambiar el valor.
  7. `lock()` pone `self._master = None` y `self._index = None`. (Python no
     garantiza borrar la memoria; documentarlo con honestidad.)
- **Pruebas:** crear, abrir, put/get, nombres invisibles en el fichero
  (`"CLOUDFLARE" not in path.read_text()`), intercambiar dos blobs de `entries`
  en el JSON → `get_value` falla, `remove_slot` del último → error.
- **Commit:** `feat(v2): VaultV2 con indice cifrado`

### Paso 1.5 - Historial de versiones y papelera

- **Cambio:** `update_value` mete el valor anterior en `history` (máximo 5,
  los más nuevos primero). `delete` no borra: mueve la entrada a
  `meta["deleted_at"] = ahora`; `list()` no las muestra salvo
  `list(include_deleted=True)`. `purge(entry_id)` borra de verdad. Las entradas
  en papelera más de 30 días se purgan al abrir el cofre.
- **Métodos nuevos:** `history(entry_id) -> list[dict]` (fechas, sin valores),
  `restore_version(entry_id, index)`, `restore(entry_id)`, `purge(entry_id)`.
- **Pruebas:** cambiar 7 veces → historial de 5; restaurar la versión 2;
  borrar, restaurar, purgar.
- **Commit:** `feat(v2): historial de valores y papelera`

### Paso 1.6 - `rekey`: cambiar la clave maestra

- **Para qué:** tras perder o revocar un pendrive. Un `cofre.json` **antiguo**
  (de un backup) todavía tiene el slot viejo; si el atacante tiene ese backup y
  el pendrive perdido, abre **ese backup**. `rekey` hace que los backups viejos
  no sirvan para los secretos **nuevos**, pero los secretos de entonces ya
  estaban en ese backup: por eso, tras perder un pendrive, además hay que
  **rotar los secretos** (Fase 5). Esto se le explica al usuario en la GUI.
- **Implementación:** con el cofre abierto, generar K' nueva; re-cifrar índice,
  entradas y checkpoint con K'; re-envolver K' en cada slot **que se pueda
  abrir ahora** (se piden los materiales: pendrives conectados y/o código de
  recuperación; los slots que no se puedan re-envolver se eliminan, avisando).
  Escribir todo de una vez con `atomic_write_text`.
- **Prueba:** tras `rekey`, el fichero de antes (copiado en la prueba) no se
  abre con K'; el nuevo sí con el pendrive.
- **Commit:** `feat(v2): rekey de la clave maestra`

### Paso 1.7 - Copias de seguridad cifradas automáticas

- **Archivo:** `cofre/v2/backups.py`.
- **Comportamiento:**
  - `rotate(path)`: antes de escribir, copia el `cofre.json` actual a
    `backups/cofre-AAAAMMDD-HHMMSS.json` junto al cofre. Guarda las 20 más
    recientes y una por día de los últimos 30 días; borra el resto.
  - Las copias ya están cifradas (son el mismo JSON v2): no hace falta más.
  - `export(dest_dir)`: copia el cofre a otra carpeta (p. ej. el pendrive de
    reserva o un disco externo) **sin** la llave. Avisar en la GUI: "la copia y
    la llave no deben ir juntas en el mismo sitio" — salvo que el usuario lo
    decida a sabiendas.
- **Prueba:** 25 escrituras → 20 copias; cada copia es JSON válido con
  `format == 2`.
- **Commit:** `feat(v2): copias de seguridad cifradas rotativas`

### Paso 1.8 - Migración v1 → v2

- **Archivo:** `cofre/v2/migrate.py` y subcomando `migrate` en el CLI.
- **Uso (lo ejecuta el USUARIO, no el LLM):**
  ```
  run.cmd migrate --dry-run         # dice que haria, no escribe
  run.cmd migrate                   # migra
  ```
- **Algoritmo:**
  1. Abrir v1 con el pendrive conectado (código existente).
  2. Copiar `cofre.json`, `.cofre-salt` y `.cofre-sticks.json` a
     `backups/v1-AAAAMMDD-HHMMSS/` y verificar que la copia se lee.
  3. Leer **la clave del pendrive conectado** y su serial; crear el v2 con un
     slot USB para él.
  4. Por cada entrada v1: `put({"name": n, "tags": tags, "type": "api_key" si
     el nombre contiene KEY/TOKEN/SECRET si no "password"}, valor)`.
  5. Escribir el v2 en `cofre.v2.json`; abrirlo de nuevo; comprobar que cada
     valor coincide con el v1 (comparación en memoria, sin imprimir).
  6. Solo si todo coincide: renombrar `cofre.json` → `cofre.v1.json` y
     `cofre.v2.json` → `cofre.json`.
  7. Mostrar el código de recuperación **una sola vez** (crear slot recovery) y
     pedir que se teclee la palabra 5 y la 17 para confirmar que lo ha apuntado.
  8. Indicar el siguiente paso: "conecta el pendrive de reserva y pulsa
     *Añadir pendrive*". **Importante:** el pendrive de reserva recibe una
     **clave nueva** (se sobrescribe su `COFRE.KEY` solo después de que el slot
     nuevo se haya guardado y probado). Pedir confirmación explícita.
- **Detección de versión:** `store.open_any(path)` mira `"format"`: si no está →
  v1; si es 2 → v2.
- **Pruebas:** migrar un v1 temporal con 5 secretos → v2 con 5 secretos iguales;
  `--dry-run` no cambia ningún fichero (comparar hashes antes/después).
- **Commit:** `feat(v2): migracion v1 a v2 con verificacion`

### Paso 1.9 - Fachada `store.py` y cambio de CLI, GUI y puente a v2

- **Objetivo:** que el resto del programa no sepa de versiones.
- **Archivo:** `cofre/store.py` con una función `open_store(vault_path, gate,
  stick, pin, allow_new)` que devuelve un `VaultV2` abierto (o lanza
  `GateUnavailable` con un mensaje claro). Si el fichero es v1, lanza
  `NeedsMigration("este cofre es v1: ejecuta run.cmd migrate")`.
- **Cambios en CLI:** cada comando usa `open_store`; `add` → `put` o
  `update_value`; `get` → `find` + `get_value`; `list` → nombres de `list()`;
  `stick-*` pasan a operar sobre slots:
  - `stick-add <ruta>`: crea clave nueva en el pendrive destino y añade slot.
  - `stick-list`: lista slots (id corto, tipo, serial, etiqueta, conectado).
  - `stick-revoke <id>`: `remove_slot` + aviso de `rekey` y rotación.
  - `recovery-new`: crea un nuevo código y borra el anterior.
  - `stick-copy` y `stick-register`: **se eliminan** (con mensaje que explique
    la alternativa). `.cofre-sticks.json` deja de usarse.
- **GUI y puente:** usan la sesión abierta (Fase 2) en vez de volver a leer el
  pendrive en cada petición.
- **Hecho cuando:** toda la batería (adaptada) pasa con cofres v2; la batería v1
  se conserva para `migrate`.
- **Commit:** `feat: CLI, GUI y puente usan cofre v2`

> **Punto de control con el usuario (M2):** el LLM para aquí. El usuario
> ejecuta `migrate --dry-run`, luego `migrate`, apunta el código de
> recuperación, añade el pendrive de reserva y prueba a abrir con cada uno y con
> el código. Solo después se continúa.

---

## 9. Fase 2 - Sesión, bloqueo y políticas por secreto

### Paso 2.1 - Objeto `Session`

- **Archivo:** `cofre/session.py`.
- **Responsabilidad:** tener el `VaultV2` abierto y decidir cuándo cerrarlo.
  ```python
  class Session:
      def __init__(self, vault: VaultV2, serial: int | None, settings: dict): ...
      def touch(self): ...               # marca actividad
      def check(self) -> str | None:     # devuelve el motivo si hay que bloquear
          # "inactividad", "tiempo maximo", "pendrive retirado", "windows bloqueado"
      def lock(self, reason: str): ...   # vault.lock(), registra en log
  ```
- La GUI llama a `session.check()` en su `_poll` (cada 2 s) y bloquea si
  devuelve algo, mostrando el motivo.
- Tiempos por defecto: inactividad 10 min, máximo 8 h (de `config`).
- **Pruebas:** con un reloj inyectable (`now=lambda: ...`) simular el paso del
  tiempo y comprobar los motivos.
- **Commit:** `feat: sesion con bloqueo por inactividad y tiempo maximo`

### Paso 2.2 - Bloquear al bloquear Windows o suspender

- **Primero una sonda** `tools/lockstate_probe.py`: cada segundo imprime si el
  escritorio de entrada se puede abrir:
  ```python
  import ctypes, time
  user32 = ctypes.windll.user32
  DESKTOP_SWITCHDESKTOP = 0x0100
  while True:
      h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
      locked = not h
      if h:
          user32.CloseDesktop(h)
      print(time.strftime("%H:%M:%S"), "BLOQUEADO" if locked else "activo", flush=True)
      time.sleep(1)
  ```
  El **usuario** la ejecuta, pulsa Win+L, vuelve, y pega la salida en PROGRESO.
- **Si la sonda distingue bien:** `Session.check()` devuelve
  `"windows bloqueado"` cuando `OpenInputDesktop` falla. Para suspensión: si
  entre dos `_poll` han pasado más de 60 s de reloj real, bloquear
  (`"el equipo estuvo suspendido"`).
- **Si no distingue:** apuntarlo y saltar (no es bloqueante).
- **Commit:** `feat: bloqueo al bloquear Windows o suspender`

### Paso 2.3 - Políticas por secreto

- Campo `policy` del índice (ver 1.1.b):
  - `confirm`: si es `true`, cualquier entrega del valor (navegador, `exec`,
    copiar) pide confirmación en la GUI (paso 2.4).
  - `browser`: si es `false`, el puente nunca lo entrega.
  - `exec`: si es `false`, `exec` no lo inyecta.
- **Valores por defecto según tipo:** `private_key` y entradas marcadas como
  "clave maestra de proveedor" (`tags` contiene `admin`) → `confirm: true,
  browser: false`. `password` → `browser: true, exec: false`. `api_key`/
  `api_token` → `browser: false, exec: true`.
- **Una única función** decide: `policy.allowed(meta, channel) -> (bool, motivo)`
  con `channel` en `{"browser", "exec", "clipboard", "reveal"}`.
- **Pruebas:** tabla de casos tipo × canal.
- **Commit:** `feat: politicas de entrega por secreto`

### Paso 2.4 - Diálogo de confirmación

- **Archivo:** `cofre/gui/confirm.py`.
- Ventana modal, siempre encima (`attributes("-topmost", True)`), que muestra:
  - **Quién pide:** "Navegador — dash.cloudflare.com" / "Terminal — `wrangler
    deploy`" / "Tú — Copiar".
  - **Qué pide:** nombre del secreto (nunca el valor).
  - Botones: **Denegar** (por defecto, con foco), **Permitir una vez**,
    **Permitir 5 minutos** (para ese secreto y ese canal).
  - Se cierra sola con "Denegar" a los 20 s.
- El puente (hilo HTTP) no puede tocar Tk: usar una `queue.Queue` que la GUI
  vacía en `_poll` (cada 200 ms mientras haya peticiones pendientes) y un
  `threading.Event` por petición para devolver la respuesta.
- **Commit:** `feat: confirmacion en pantalla para secretos sensibles`

---

## 10. Fase 3 - Auditoría a prueba de manipulación y detección de intrusos

### Paso 3.1 - Log encadenado

- **Archivo:** reescribir `cofre/audit.py` conservando las funciones públicas
  (`record`, `tail`, `tail_human`, `stats`) para no romper llamadas.
- **Formato nuevo** `.cofre-audit.jsonl` (una línea JSON por evento):
  ```json
  {"seq": 41, "ts": "2026-11-20T10:00:00", "ev": "get", "entry": "uuid o -",
   "name": "CLOUDFLARE_DNS_TOKEN", "actor": "browser:dash.cloudflare.com",
   "ok": true, "detail": "", "prev": "sha256 hex de la linea 40", "mac": "hmac hex o null"}
  ```
  - `prev` = SHA-256 de la línea anterior completa (texto exacto). La primera
    línea usa `"0"*64`.
  - `mac` = HMAC-SHA256 con `subkey(K, b"audit")` del JSON sin el campo `mac`
    (`json.dumps(..., sort_keys=True, separators=(",", ":"))`). Si el cofre está
    cerrado (p. ej. un intento fallido), `mac` es `null`.
  - `actor`: `gui`, `cli`, `exec:<primer argumento del comando>`,
    `browser:<host>`.
- **Checkpoint:** cada vez que el cofre está abierto y se escribe, guardar en
  `checkpoint` cifrado del cofre `{"seq": ultimo, "hash": sha256_ultima_linea}`.
  Así, si alguien borra las últimas líneas del log, al abrir se detecta.
- **Verificación:** `run.cmd log verify` recorre el fichero, comprueba la cadena
  `prev`, los `mac` no nulos y el checkpoint. Imprime `OK` o la primera línea
  rota. La GUI lo ejecuta al abrir y avisa si falla.
- **Rotación:** al pasar de 5000 líneas, renombrar a
  `.cofre-audit-AAAAMMDD.jsonl` y empezar uno nuevo cuya primera línea `prev`
  sea el hash de la última del anterior.
- **Pruebas:** borrar una línea del medio → `verify` falla; editar un `name` →
  falla; truncar el final → falla por checkpoint.
- **Commit:** `feat: log de auditoria encadenado con HMAC y checkpoint`

### Paso 3.2 - Reglas de alerta

- **Archivo:** `cofre/alerts.py`, función `evaluate(recent_events, settings) ->
  list[Alert]`.
- **Reglas iniciales:**

| Regla | Disparo | Gravedad |
|---|---|---|
| Ráfaga | más de 10 lecturas de valores en 5 minutos | alta |
| Señuelo | cualquier lectura de una entrada `type == "canary"` | crítica |
| Fallos de apertura | 3 fallos seguidos | media |
| Hora rara | lectura entre las 01:00 y las 06:00 (configurable) | baja |
| Puente | petición con token inválido o de origen no autorizado | media |
| Log manipulado | `log verify` falla | crítica |

- **Cómo avisa:** banda roja/ámbar en la GUI con el texto y un botón "Ver
  detalle"; en alertas altas o críticas, además, `MessageBoxW` con
  `MB_TOPMOST | MB_ICONWARNING` (ctypes, sin dependencias). La alerta crítica
  ofrece directamente el **botón de pánico** (Fase 5).
- **Commit:** `feat: alertas por comportamiento anomalo`

### Paso 3.3 - Credenciales señuelo (honeytokens)

- **Qué es:** una credencial falsa que parece real y que avisa por email si
  alguien la usa. Si un atacante roba tus ficheros y prueba las claves, te
  enteras.
- **Instrucciones para el usuario (no las hace el LLM):**
  1. Crear 1-2 señuelos gratuitos en canarytokens.org (por ejemplo, del tipo
     "AWS API key"), con tu email de alerta.
  2. Guardarlos en COFRE con tipo `canary` y nombre creíble
     (`AWS_PROD_ACCESS_KEY`).
  3. Opcional: poner un fichero `.env.backup` falso en una carpeta de proyecto
     con el señuelo dentro.
- **Lo que hace el código:** el tipo `canary` no se puede copiar ni rellenar ni
  inyectar (política fija); cualquier `get_value` sobre él dispara la alerta
  crítica.
- **Commit:** `feat: tipo de entrada senuelo`

### Paso 3.4 - Escáner de fugas sin revelar nada

- **Comando:** `run.cmd scan <carpeta>`.
- **Algoritmo:** recorrer ficheros de texto (< 2 MB, saltando `.git`,
  `node_modules`, `.venv`, binarios); extraer candidatos con la expresión
  `[A-Za-z0-9_\-\.=+/]{16,}`; para cada candidato calcular el HMAC con la clave
  de huellas y compararlo con los `fingerprint` del índice. Informe:
  `archivo:línea  NOMBRE_DEL_SECRETO` — **nunca** el valor.
- **Gancho de git opcional:** `run.cmd scan --install-hook <repo>` escribe
  `.git/hooks/pre-commit` que ejecuta `scan --staged` y bloquea el commit si
  encuentra algo. Requiere el cofre abierto; si está cerrado, el gancho avisa y
  deja pasar (no bloquear el trabajo por eso).
- **Commit:** `feat: escaner de fugas por huellas HMAC`

---

## 11. Fase 4 - Navegador profesional

### Paso 4.0 - Sonda: mensajería nativa con `.bat` **[DECISIÓN]**

- **Por qué:** la decisión de usar un servidor TCP se basó en que Chrome no
  ejecuta un `.cmd` como host. La documentación de Chrome dice que en Windows la
  ruta del host puede ser relativa al manifiesto, y MDN propone justamente un
  `.bat` que llama a Python. Sin puerto TCP, ningún programa puede "llamar al
  puerto"; Chrome solo deja hablar al host con las extensiones de
  `allowed_origins`.
- **Sonda** `tools/nm_probe/`:
  - `host.bat`: `@echo off` + `python -u "%~dp0host.py"`
  - `host.py`: lee mensajes con el formato de Chrome (4 bytes little-endian de
    longitud + JSON por stdin) y responde `{"pong": true}`. **Nada** por stdout
    salvo los mensajes (los logs a un fichero).
  - `com.cofre.probe.json` con `"path": "host.bat"`, `"type": "stdio"` y
    `"allowed_origins": ["chrome-extension://<ID>/"]`.
  - Registrar en
    `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.cofre.probe` con valor
    por defecto = ruta completa del JSON (`reg add ... /ve /d ... /f`).
  - Añadir temporalmente `"nativeMessaging"` a los permisos de la extensión y,
    desde la consola del service worker, `chrome.runtime.sendNativeMessage(
    "com.cofre.probe", {ping: 1}, console.log)`.
- **Resultado:** el usuario pega lo que sale. Decisión en la sección 18 (D3):
  - **Funciona:** en una fase posterior, el host nativo sustituye al puerto TCP:
    el host habla con la GUI por una tubería con nombre (`\\.\pipe\cofre-<usuario>`)
    con las cuatro reglas de [[COFRE-INTEGRACION-2026-11-13]] §3.
  - **No funciona:** se sigue con el puerto TCP y se aplica el paso 4.4.
- En ambos casos los pasos 4.1-4.3 y 4.5-4.8 son iguales.

### Paso 4.1 - Inyección solo bajo demanda

- `manifest.json`: **quitar** el bloque `content_scripts`. Permisos:
  `["activeTab", "scripting", "storage"]`; `host_permissions`:
  `["http://127.0.0.1/*"]`. (Quitar `clipboardWrite` si no se usa.)
- `content.js` deja de existir como script permanente: su lógica pasa a una
  función `cofreFill` que se inyecta con `chrome.scripting.executeScript` solo
  cuando el usuario pulsa Rellenar o el atajo.
- **Commit:** `feat(ext): inyeccion bajo demanda, sin scripts en todas las webs`

### Paso 4.2 - Vinculación secreto ↔ dominio (anti-phishing)

- **Datos:** `urls` del índice guarda **solo nombres de host**: `github.com`,
  `dash.cloudflare.com`, o comodín explícito `*.ejemplo.com`. Validar al
  guardar: sin `http`, sin `/`, sin espacios, en minúsculas.
- **Regla de coincidencia (idéntica en Python y en JS):**
  ```python
  from urllib.parse import urlsplit

  def host_matches(page_url: str, patterns: list[str]) -> bool:
      u = urlsplit(page_url)
      host = (u.hostname or "").lower().rstrip(".")
      if u.scheme != "https" and host not in ("localhost", "127.0.0.1"):
          return False
      for p in patterns:
          p = p.strip().lower()
          if p.startswith("*."):
              base = p[2:]
              if host == base or host.endswith("." + base):
                  return True
          elif host == p:
              return True
      return False
  ```
  Pruebas obligatorias: `https://github.com/login` ✓ con `github.com`;
  `https://github.com.evil.io` ✗; `https://evilgithub.com` ✗;
  `http://github.com` ✗; `https://gist.github.com` ✗ con `github.com` y ✓ con
  `*.github.com`.
- **Puente:** nuevo `POST /match {"url": ...}` → lista de entradas cuyo `urls`
  coincide (nombre, usuario, tipo; nunca valores). `POST /get` exige `{"id",
  "url"}` y **vuelve a comprobar** `host_matches` en el servidor; si no
  coincide → 403 `"este secreto no está autorizado para este sitio"`.
- La URL la obtiene el **service worker** con `chrome.tabs.query`, nunca la
  página.
- **Commit:** `feat: secretos vinculados a dominios, rechazo de phishing`

### Paso 4.3 - El valor no pasa por el popup

- `background.js` hace todo: pide el valor y lo inyecta. El popup solo envía
  `{type: "fill", id}`.
  ```js
  async function fillActiveTab(entryId) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url) return { ok: false, error: "no hay pestaña activa" };
    const res = await call("/get", { method: "POST",
      body: JSON.stringify({ id: entryId, url: tab.url }) });
    if (!res.ok) return res;
    const [inj] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [0] },
      func: cofreFill,
      args: [res.username || "", res.value, tab.url],
    });
    return inj?.result || { ok: false, error: "no se pudo rellenar" };
  }
  ```
- `cofreFill(username, value, expectedUrl)` **dentro de la página**:
  1. Si `new URL(location.href).origin !== new URL(expectedUrl).origin` →
     devolver error (la página navegó entre medias).
  2. Buscar `input[type=password]` visibles del documento principal.
  3. Usuario: el `input[type=email]`, `input[autocomplete=username]` o el
     `input[type=text]` visible inmediatamente anterior al de contraseña en el
     mismo `form`.
  4. Rellenar con el setter nativo para que React/Vue lo detecten:
     ```js
     const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
     setter.call(el, value);
     el.dispatchEvent(new Event("input", { bubbles: true }));
     el.dispatchEvent(new Event("change", { bubbles: true }));
     ```
  5. **No** enviar el formulario. Devolver `{ok: true, filled: n}`.
- **Commit:** `feat(ext): relleno desde el service worker`

### Paso 4.4 - Emparejamiento y token del puente (solo si se queda el TCP)

- Al activar el puente, la GUI genera un **código de 6 dígitos** y lo muestra
  grande ("Escribe este código en la extensión: 481 203").
- La extensión, si no tiene token en `chrome.storage.session`, muestra un campo
  para el código y hace `POST /pair {"code": "481203"}`.
- El servidor compara con `hmac.compare_digest`; tras 5 fallos, invalida el
  código y avisa en la GUI (alerta "Puente"). Si acierta, devuelve un token
  `secrets.token_hex(32)` y el código deja de valer.
- Todas las demás rutas exigen `Authorization: Bearer <token>` (comparación con
  `hmac.compare_digest`) **además** del `Origin`.
- El token muere al bloquear el cofre o parar el puente. `chrome.storage.session`
  se borra al cerrar el navegador.
- Límite: 30 peticiones por minuto; por encima → 429 y alerta.
- **Honestidad (texto para la guía):** un malware de tu misma sesión podría,
  con mucho esfuerzo, leer la memoria del navegador o de la GUI. El token
  eleva el listón frente a scripts simples que llaman al puerto; la confirmación
  (2.4) y el log (3.1) son las defensas de fondo.
- **Commit:** `feat: emparejamiento por codigo y token para el puente`

### Paso 4.5 - Confirmación en el navegador

- Si `policy.confirm` es `true`, `/get` espera la respuesta del diálogo 2.4
  (máximo 25 s) antes de contestar. El popup muestra "Confirma en la ventana de
  COFRE…".
- **Commit:** `feat: confirmacion de entregas al navegador`

### Paso 4.6 - Popup profesional

- **Diseño (de arriba abajo):**
  1. Cabecera: punto de estado (verde abierto / gris cerrado) + "COFRE" + host
     de la pestaña actual.
  2. **Sugeridos para este sitio** (resultado de `/match`): filas grandes con
     nombre, usuario y botón **Rellenar**. Si hay uno solo, Enter lo rellena.
  3. Buscador.
  4. "Otros secretos" plegado; al rellenar uno que no coincide con el dominio,
     el servidor lo rechaza y el popup ofrece **"Asignar este sitio a X"**, que
     abre la confirmación en la GUI (nunca se asigna desde la extensión sola).
  5. Pie: "Bloquear cofre" y "Abrir COFRE".
- Insignia del icono con `chrome.action.setBadgeText`: texto vacío cuando el
  cofre está abierto y `"off"` (fondo gris) cuando está cerrado.
- Atajo de teclado (`commands` en el manifiesto): `Ctrl+Shift+L` → rellena el
  primer sugerido si hay exactamente uno; si hay varios, abre el popup.
- **Commit:** `feat(ext): popup con sugeridos por sitio y atajo`

### Paso 4.7 - Generar contraseña en una web de registro

- En el popup, si la página tiene `input[autocomplete=new-password]` o dos campos
  de contraseña: botón **"Generar y guardar"**.
- Flujo: la extensión pide a la GUI `POST /generate {"url"}`; la GUI genera
  (perfil humano 6 palabras o máquina, según ajuste), **crea la entrada con el
  dominio ya asignado**, pide confirmación (2.4) y devuelve el valor para
  rellenar los dos campos. Así nunca queda una contraseña nueva sin guardar.
- **Commit:** `feat: generar y guardar desde el navegador`

### Paso 4.8 - Guardar un login existente (sin capturar del DOM)

- **No** se captura lo que el usuario teclea en la web (riesgo y complejidad).
- En su lugar: botón "Guardar este sitio en COFRE" en el popup → abre en la GUI
  el diálogo de nuevo secreto con `urls` y, si se ve, el usuario rellenados. El
  valor se escribe **en la GUI**.
- **Commit:** `feat: alta rapida desde el navegador`

---

## 12. Fase 5 - Ciclo de vida y rotación de credenciales

### 12.0 Cómo se rota bien (léelo antes de programar)

Rotar no es "cambiar la clave". Es este ciclo de **dos fases**, que nunca deja
a un consumidor sin una clave válida:

```
1. CREAR nueva credencial en el proveedor (la vieja sigue viva)
2. GUARDAR la nueva en COFRE como "pendiente" (la vieja sigue siendo la activa)
3. DESPLEGAR la nueva en cada consumidor (GitHub Actions, Worker...)
4. VERIFICAR que la nueva funciona (llamada de prueba al proveedor)
5. PROMOVER: la nueva pasa a activa; la vieja va al historial
6. REVOCAR la vieja en el proveedor
7. REGISTRAR todo en el log
```

Si falla 3 o 4: **deshacer** (borrar la nueva en el proveedor, quitar la
pendiente). Si el programa se cae a mitad, al volver a abrir debe saber en qué
punto estaba: por eso existe un **diario de rotación** dentro del cofre.

### Paso 5.1 - Metadatos de ciclo de vida en la GUI y el CLI

- Los campos ya existen en el índice v2 (1.1.b). Este paso los hace editables:
  - CLI: `run.cmd meta NOMBRE --provider cloudflare --token-id XXX
    --expires 2027-02-20 --rotate-every 90 --url dash.cloudflare.com
    --consumer gha:usuario/repo:CF_API_TOKEN`.
  - GUI: sección "Ciclo de vida" en el detalle (ver Fase 6).
- `consumers` es una lista de cadenas con formato `tipo:destino:nombre`:
  - `gha:propietario/repo:NOMBRE_DEL_SECRETO` (GitHub Actions, repo)
  - `gha-env:propietario/repo:entorno:NOMBRE` (GitHub Actions, entorno)
  - `cfw:account_id:script:NOMBRE` (secreto de un Cloudflare Worker)
  - `exec` (solo se usa con `run.cmd exec`: nada que desplegar)
  - `manual:texto libre` (el usuario lo actualiza a mano; COFRE le recuerda)
- **Commit:** `feat: metadatos de proveedor, caducidad y consumidores`

### Paso 5.2 - Interfaz de proveedores y cliente HTTP

- **Archivos:** `cofre/providers/__init__.py`, `base.py`, `http.py`.
- **`http.py`:** función única `request(method, url, headers, json_body=None,
  timeout=20) -> (status, headers_dict, body_dict_or_text)` con
  `urllib.request`. **Nunca** registrar cabeceras ni cuerpos (llevan secretos).
  Errores de red → excepción `ProviderError` con mensaje en español sin el
  valor.
- **`base.py`:**
  ```python
  class Provider:
      name = "base"
      can_auto_rotate = False
      def verify(self, value: str, meta: dict) -> dict:
          """{'ok': bool, 'expires_at': 'AAAA-MM-DD' o '', 'detail': str}"""
      def create_replacement(self, meta: dict, admin_value: str) -> tuple[str, dict]:
          """Crea una credencial nueva equivalente. Devuelve (valor, provider_ref nuevo)."""
      def revoke(self, value: str, meta: dict, admin_value: str) -> None: ...
      def manual_url(self, meta: dict) -> str:
          """Pagina web donde el usuario rota a mano."""
  REGISTRY: dict[str, Provider] = {}
  ```
- **Commit:** `feat: interfaz de proveedores`

### Paso 5.3 - Proveedor Cloudflare (rotación automática)

- **Credenciales implicadas:**
  - El token que se usa (`CLOUDFLARE_DNS_TOKEN`, etc.).
  - Un **token administrador** guardado aparte (`CLOUDFLARE_TOKEN_ADMIN`) con el
    permiso de gestionar tokens de API ("API Tokens Write"), política
    `confirm: true, browser: false, exec: false`. Es el secreto más delicado.
- **verify:** `GET https://api.cloudflare.com/client/v4/user/tokens/verify` con
  `Authorization: Bearer <valor>`. OK si `success` y `result.status ==
  "active"`; `expires_on` si viene.
- **Rotación, dos variantes:**
  - **A — sin consumidores desplegados (solo `exec`):** "roll" del token:
    `PUT /client/v4/user/tokens/{token_id}/value` con cuerpo `{}` y el token
    administrador; la respuesta trae el valor nuevo en `result`. Para tokens de
    cuenta: `PUT /client/v4/accounts/{account_id}/tokens/{token_id}/value`.
    Ojo: tras el roll, asume que el valor viejo deja de valer al momento
    (compruébalo con un token de pruebas antes de usarlo en real).
  - **B — con consumidores (GitHub Actions, Workers):** dos fases reales:
    1. `GET /user/tokens/{token_id}` → leer `name`, `policies`, `condition`,
       `expires_on`.
    2. `POST /user/tokens` con las mismas `policies` y `condition`, nombre
       `"<nombre> (rotado AAAA-MM-DD)"` y `expires_on` = hoy +
       `rotate_every_days` + 14 días de margen.
    3. Desplegar en consumidores, verificar, promover.
    4. `DELETE /user/tokens/{token_id_viejo}`.
- **Recomendaciones que la GUI muestra al dar de alta un token de Cloudflare:**
  permisos mínimos; limitar por IP (`condition.request_ip.in`) cuando el uso es
  desde tu equipo; poner fecha de caducidad; un token por consumidor.
- **Pruebas:** con un servidor HTTP falso local (`http.server` en un hilo) que
  imite las respuestas; **no** llamar a Cloudflare real desde los tests.
- **Prueba real (la hace el usuario):** crear un token de prueba sin permisos
  útiles, guardarlo con `--provider cloudflare --token-id ...`, ejecutar
  `run.cmd rotate NOMBRE --dry-run` y luego sin `--dry-run`.
- **Commit:** `feat: proveedor Cloudflare con verificacion y rotacion`

### Paso 5.4 - Proveedor GitHub (rotación asistida + tokens de 1 hora)

- **Hecho importante:** a fecha de este plan, GitHub **no** ofrece una API
  pública para crear tokens personales (PAT); se crean en la web. Antes de
  implementar, el LLM comprueba en la documentación oficial que sigue siendo así
  y lo anota en PROGRESO. Por eso hay dos caminos.
- **Camino 1 — PAT con rotación asistida (para lo que ya tienes):**
  1. **verify:** `GET https://api.github.com/user` con `Authorization: Bearer
     <valor>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2026-03-10`. OK si 200. Si la respuesta trae la
     cabecera `github-authentication-token-expiration`, guardar esa fecha en
     `expires_at` (si no la trae, no inventar).
  2. **Rotar:** la GUI abre `https://github.com/settings/personal-access-tokens`
     en el navegador, con instrucciones: "crea uno nuevo con los mismos
     permisos, cópialo, vuelve y pulsa *Pegar nuevo*". El valor se pega en la
     GUI (campo oculto), COFRE lo verifica, despliega en consumidores, promueve.
  3. **Revocar el viejo:** `POST https://api.github.com/credentials/revoke` con
     cuerpo `{"credentials": ["<valor viejo>"]}` y **sin** cabecera
     `Authorization` (esta API devuelve 403 si va autenticada; está pensada para
     credenciales expuestas). Respuesta esperada: 202. Además, recordar al
     usuario borrar el token viejo en la página de ajustes.
- **Camino 2 — GitHub App (recomendado para automatizar; sin rotación):**
  1. El usuario crea una GitHub App propia, la instala en sus repos y descarga la
     clave privada `.pem`. La guarda en COFRE como `private_key`
     (`GITHUB_APP_KEY`), con `fields: {"app_id": "...", "installation_id": "..."}`
     y política `confirm: false, browser: false, exec: false`.
  2. `run.cmd exec --name GITHUB_TOKEN@app -- gh ...`: COFRE firma un JWT RS256
     (`iat` = ahora − 60 s, `exp` = ahora + 9 min, `iss` = app_id) con
     `cryptography` y llama a
     `POST https://api.github.com/app/installations/{installation_id}/access_tokens`
     con `Authorization: Bearer <JWT>`. El token devuelto caduca a la hora: se
     inyecta en el proceso y **no se guarda**.
  3. Ventaja: si te roban ese token, sirve una hora como mucho.
- **Pruebas:** firma del JWT verificable con la clave pública en el test;
  servidor falso para las llamadas.
- **Commit:** `feat: proveedor GitHub (PAT asistido y GitHub App)`

### Paso 5.5 - Proveedor genérico (cualquier API)

- Para OpenAI, Anthropic, Tavily, Hugging Face, etc.: rotación **manual
  asistida** + **verificación configurable**:
  ```json
  "verify": {"method": "GET", "url": "https://api.ejemplo.com/v1/me",
             "header": "Authorization", "prefix": "Bearer ", "ok_status": [200]}
  ```
  guardado en `provider_ref`. El usuario lo rellena en la GUI con su
  documentación delante. El LLM **no** inventa URLs de verificación de
  proveedores: deja ejemplos vacíos.
- `manual_url` también lo pone el usuario (página de claves del proveedor).
- **Commit:** `feat: proveedor generico con verificacion configurable`

### Paso 5.6 - Consumidores: desplegar el valor nuevo

- **Archivo:** `cofre/consumers.py`, función
  `deploy(consumer: str, value: str, vault) -> None`.
- **`gha:` (GitHub Actions):**
  1. `GET /repos/{owner}/{repo}/actions/secrets/public-key` → `key_id`, `key`.
  2. Cifrar con caja sellada de libsodium (necesita **PyNaCl**, apéndice 19.5):
     ```python
     from base64 import b64encode
     from nacl import encoding, public
     def seal_for_github(public_key_b64: str, value: str) -> str:
         pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
         return b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()
     ```
  3. `PUT /repos/{owner}/{repo}/actions/secrets/{NOMBRE}` con
     `{"encrypted_value": ..., "key_id": ...}` → 201 o 204.
  4. Credencial para hacerlo: un token de GitHub con permiso sobre "Secrets" de
     ese repo (o el token de 1 hora de la GitHub App del paso 5.4).
  5. Para `gha-env:` la ruta es la de secretos de entorno; **el LLM debe
     consultar la documentación oficial** antes de implementarlo y anotar la URL
     en PROGRESO.
- **`cfw:` (Cloudflare Workers):** usar la API de secretos de scripts de Workers.
  **Consultar la documentación oficial** de Cloudflare y anotar la ruta exacta
  en PROGRESO antes de programar; no adivinarla.
- **`manual:`** no despliega: añade a la lista "tareas manuales" que la GUI
  muestra con casilla "Hecho".
- Si PyNaCl no está instalado: `gha:` lanza `ProviderError("falta PyNaCl:
  pip install pynacl")` y la rotación no empieza.
- **Commit:** `feat: despliegue en GitHub Actions y Workers`

### Paso 5.7 - Motor de rotación con diario

- **Archivo:** `cofre/rotation.py`.
- **Estados** (guardados en `index.settings.rotation_journal[entry_id]`):
  `created → stored_pending → deployed → verified → promoted → old_revoked → done`
  y `failed:<estado>` / `rolled_back`.
- **Función principal:** `rotate(vault, entry_id, *, dry_run=False, confirm=callable)`.
  - Antes de empezar: comprobar política, proveedor, credencial admin
    disponible, consumidores desplegables. Con `dry_run`, imprimir el plan paso
    a paso y salir.
  - Tras cada estado: guardar el diario en el cofre (escritura atómica).
  - Al abrir el cofre, si hay diarios sin `done`: la GUI muestra "Hay una
    rotación a medias de X: Continuar / Deshacer".
- **Comandos:** `run.cmd rotate NOMBRE [--dry-run]`, `run.cmd rotate --due`
  (todas las que tocan, una a una, pidiendo confirmación).
- **Pruebas:** proveedor y consumidor falsos que fallan en cada estado →
  comprobar que deshace o reanuda correctamente.
- **Commit:** `feat: motor de rotacion en dos fases con diario`

### Paso 5.8 - Calendario y recordatorios

- **Problema:** las fechas están dentro del cofre cifrado; sin pendrive no se
  pueden leer. **Solución:** al cerrar el cofre, escribir
  `cofre-schedule.json` (no secreto) con `{"next_due": "AAAA-MM-DD", "count":
  N}` — **sin nombres**. Si alguien lo manipula, solo afecta al recordatorio.
- **Tarea programada de Windows** (la crea el usuario con un comando que el
  plan le da):
  ```
  schtasks /Create /SC DAILY /ST 10:17 /TN "COFRE recordatorio" ^
    /TR "\"C:\Users\Sammi\AI\cofre\.venv\Scripts\pythonw.exe\" -m cofre.cli due --notify"
  ```
  (ajustar la ruta de `pythonw.exe` a la real; comprobarla con `where pythonw`).
- `due --notify`: lee el schedule; si `next_due <= hoy`, muestra
  `MessageBoxW`: "COFRE: N credenciales necesitan rotación o caducan pronto.
  Conecta el pendrive y abre COFRE." Si no, no hace nada.
- **Commit:** `feat: recordatorios de rotacion sin abrir el cofre`

### Paso 5.9 - Salud de las credenciales

- `run.cmd health` (y panel en la GUI): para cada entrada con proveedor,
  `verify` y clasificar:
  - **Inválida** (el proveedor la rechaza) — rojo.
  - **Caduca en < 14 días** — ámbar.
  - **Rotación vencida** (`last_rotated + rotate_every_days < hoy`) — ámbar.
  - **Sin verificar hace > 30 días** — gris.
  - **Duplicada** (misma `fingerprint` en dos entradas) — ámbar: "el mismo
    valor se usa en dos sitios".
  - **Contraseña débil** (< 60 bits estimados) — ámbar.
- Guardar `last_verified`. Nunca mostrar valores.
- **Commit:** `feat: comprobacion de salud de credenciales`

### Paso 5.10 - Botón de pánico

- `run.cmd panic` y botón rojo en la GUI (Ajustes → Emergencia), protegido:
  hay que teclear `REVOCAR TODO`.
- **Qué hace, en este orden, con informe en pantalla y en el log:**
  1. Cloudflare con admin disponible: roll (variante A) de **todos** sus tokens
     registrados; el token admin se rota el **último**.
  2. GitHub PAT: `POST /credentials/revoke` con todos los PAT guardados (máx.
     1000 por llamada).
  3. GitHub App: indicar al usuario que regenere la clave privada en la web.
  4. Genéricos: lista de `manual_url` para hacerlo a mano, con casillas.
  5. Señuelos: no se tocan.
  6. Crear un código de recuperación nuevo y hacer `rekey`.
- **Antes de implementar:** `panic --dry-run` muestra la lista sin tocar nada.
  El usuario debe probar `--dry-run` primero.
- **Commit:** `feat: boton de panico`

---

## 13. Fase 6 - UX/UI profesional

**Relación con los planes anteriores:** [[COFRE-PLAN-UX-2026-11-10]] (fases 0-4,
casi todo hecho) y [[COFRE-PLAN-ESTETICA-2026-11-10]] (fase A hecha; B-E
pendientes). Este capítulo **sustituye** a las fases B-E de estética por una
estructura nueva, pero **reutiliza** los tokens de `cofre/theme.py` y las
herramientas `tools/layout_check.py`, `tools/theme_check.py`,
`tools/spacing_sweep.py`. Antes de empezar, lee esos dos planes y apunta en
PROGRESO qué partes de B-E siguen teniendo sentido.

**Decisión de tecnología:** se queda **Tkinter** (sin dependencias, sin abrir
puertos para una interfaz web). Se pueden usar los widgets `ttk` donde mejoren
(Treeview para la lista, Notebook para pestañas), estilados con los tokens.

### Paso 6.1 - Nueva arquitectura de la ventana

```
┌──────────────────────────────────────────────────────────────────────────┐
│ COFRE   [ Buscar… Ctrl+K                     ]   ● abierto · E: · 9:42 ⏻ │  cabecera
├───────────────┬──────────────────────────────┬───────────────────────────┤
│ TODOS      42 │ ▸ CLOUDFLARE_DNS_TOKEN   ⚠  │ CLOUDFLARE_DNS_TOKEN      │
│ Contraseñas 18│   GITHUB_PAT_DEPLOY        │ api_token · cloudflare    │
│ Claves API  21│   TAVILY_API_KEY           │ ───────────────────────── │
│ Notas        3│   …                        │ Valor  ••••••••••  👁 ⧉   │
│ ───────────── │                            │ Sitios dash.cloudflare.com│
│ ⚠ Atención   4│                            │ Usado en  gha:yo/web      │
│ ⟳ Rotar      2│                            │ ───────────────────────── │
│ ⌛ Caducan    1│                            │ Ciclo de vida             │
│ 🗑 Papelera   0│                            │ Caduca 20-feb · Rotado    │
│ ───────────── │                            │ hace 12 d · cada 90 d     │
│ Salud         │                            │ [Verificar] [Rotar ahora] │
│ Pendrives     │                            │ ───────────────────────── │
│ Registro      │                            │ Historial (3) · Notas     │
│ Ajustes       │                            │ [Editar] [Borrar]         │
├───────────────┴──────────────────────────────┴───────────────────────────┤
│ ✓ Copiado. Se borra del portapapeles en 27 s                 [Deshacer]  │  barra de estado
└──────────────────────────────────────────────────────────────────────────┘
          [+ Nuevo]  (botón flotante o en la cabecera, Ctrl+N)
```

- **Columna 1 (filtros):** categorías por tipo, vistas inteligentes
  (Atención = inválidas + caducan + rotar + débiles), y secciones de gestión.
- **Columna 2 (lista):** `ttk.Treeview` con nombre, icono de estado y proveedor.
  Teclado: flechas, Enter = copiar (respetando política), Supr = papelera.
- **Columna 3 (detalle):** lectura por secciones; **sin** formulario de alta
  permanente (el formulario actual ocupa media ventana: se va a un diálogo).
- **Barra de estado:** mensajes breves con cuenta atrás; sustituye al pie largo
  actual. Los mensajes se toman del catálogo (paso 6.3).
- **Ancho mínimo:** 1000×640; a menos de 1100 px la columna 3 pasa a ocupar la
  2 al seleccionar (vista "pila"), con botón "← Volver".
- **Implementación:** `cofre/gui/layout.py` (marco de 3 columnas) + una vista
  por archivo. Hacer este paso **en ramas pequeñas**: primero el marco vacío con
  la lista y el detalle actuales dentro; luego cada sección.
- **Commit(s):** `feat(gui): marco de tres columnas`, `feat(gui): lista con Treeview`, …

### Paso 6.2 - Diálogo "Nuevo / Editar" por tipo

- Ventana modal de 560 px de ancho, con selector de tipo arriba (Contraseña web,
  Clave API, Token de proveedor, Nota segura, Clave privada).
- Campos por tipo:

| Tipo | Campos |
|---|---|
| Contraseña web | Nombre, Usuario, Contraseña (+ generar), Sitios, Notas |
| Clave API | Nombre (formato `MAYUS_CON_GUIONES`), Valor, Proveedor, Verificación, Usado en, Rotar cada, Caduca |
| Token de proveedor | Como Clave API + ID del token / cuenta |
| Nota segura | Nombre, Texto (multilínea) |
| Clave privada | Nombre, Fichero (se lee y se guarda; el fichero original **no** se borra solo: se ofrece hacerlo) |

- Validación en vivo con mensajes debajo del campo (no en el pie).
- El generador se integra junto al campo valor: botón "Generar ▾" con las
  opciones (máquina 384 bits / 6 palabras / 8 palabras) y la entropía al lado.
- `Esc` cancela, `Ctrl+Enter` guarda.
- **Commit:** `feat(gui): dialogo de alta y edicion por tipo`

### Paso 6.3 - Catálogo de mensajes y tono

- **Archivo:** `cofre/messages.py` con un diccionario `MSG = {"clave": "texto"}`.
  Toda cadena que ve el usuario sale de aquí (facilita revisarlas juntas).
- **Reglas de redacción:**
  1. Decir qué pasó y qué hacer: "No encuentro el pendrive. Conéctalo y pulsa
     Abrir." — no "GateUnavailable: StickNotFound".
  2. Sin jerga en la GUI (`AES`, `scrypt`, `serial` solo en "Detalles técnicos").
  3. Frases cortas; tuteo; sin signos de exclamación salvo en alertas.
  4. Los errores técnicos completos van al log y a un botón "Copiar detalle".
- **Commit:** `refactor(gui): catalogo de mensajes`

### Paso 6.4 - Paleta de comandos y atajos coherentes

- `Ctrl+K`: paleta que busca **secretos y acciones** ("Rotar CLOUDFLARE…",
  "Bloquear", "Nuevo", "Comprobar salud"). Enter ejecuta.
- Tabla de atajos (y overlay con `?` o `F1`):

| Atajo | Acción |
|---|---|
| Ctrl+K | Paleta |
| Ctrl+F | Buscar en la lista |
| Ctrl+N | Nuevo |
| Enter | Copiar valor del seleccionado |
| Ctrl+Shift+C | Copiar usuario |
| Ctrl+E | Editar |
| Supr | A la papelera |
| Ctrl+L | Bloquear |
| Esc | Ocultar valor / cerrar diálogo |
| Ctrl+Q | Salir |

- **Commit:** `feat(gui): paleta de comandos y atajos`

### Paso 6.5 - Panel "Salud"

- Tarjetas arriba: **Inválidas**, **Caducan pronto**, **Rotación vencida**,
  **Débiles**, **Repetidas**; cada una con número y clic → filtra la lista.
- Debajo: botón "Comprobar ahora" (ejecuta 5.9 con barra de progreso, en un hilo;
  la GUI no se congela) y "Rotar todas las vencidas".
- **Commit:** `feat(gui): panel de salud`

### Paso 6.6 - Pantalla "Pendrives y recuperación"

- Lista de llaves (slots) con: etiqueta, tipo (pendrive / código en papel),
  conectado sí/no, último uso.
- Acciones: **Añadir pendrive** (asistente de 3 pasos con advertencias),
  **Dar de baja** (con explicación de `rekey` y oferta de hacerlo), **Nuevo
  código de recuperación**, **Probar código de recuperación** (pide las 25
  palabras y dice si abre, sin cambiar nada).
- **Commit:** `feat(gui): gestion de llaves y recuperacion`

### Paso 6.7 - Pantalla "Ajustes"

- Secciones: Seguridad (tiempos de bloqueo, portapapeles, revelar), Navegador
  (puente on/off al abrir, emparejar de nuevo), Generador (perfil por defecto,
  idioma), Copias (carpeta de exportación), Emergencia (pánico), Acerca de
  (versión, formato del cofre, ruta).
- Guardar en `cofre-settings.json` (no secreto) con `atomic_write_text`.
- **Commit:** `feat(gui): pantalla de ajustes`

### Paso 6.8 - Asistente de primer uso v2

1. Bienvenida: qué es COFRE y qué protege (3 frases honestas).
2. Pendrive principal: elegir unidad → crear llave → crear cofre.
3. Código de recuperación: mostrar 25 palabras grandes, botón "Imprimir"
   (genera un `.txt` temporal, abre el diálogo de impresión con
   `os.startfile(ruta, "print")` y **borra** el `.txt` después), confirmar
   tecleando 2 palabras al azar.
4. Pendrive de reserva (opcional, recomendado).
5. Extensión del navegador (opcional): enlace a la guía.
- **Commit:** `feat(gui): asistente de primer uso v2`

### Paso 6.9 - Pulido visual y accesibilidad

- Revisar con `tools/theme_check.py` que todo color sale de `COLORS` y que el
  contraste texto/fondo es ≥ 4.5:1.
- Foco visible en todos los controles (borde de acento de 2 px).
- Todo se puede hacer con teclado (probar desenchufando el ratón).
- Tamaños de fuente respetan el escalado de Windows (ya existe
  `enable_dpi_awareness`).
- Estados vacíos con una frase y una acción (ya existe para la lista; replicar).
- **Commit:** `style(gui): foco visible, contraste y estados vacios`

### Paso 6.10 (opcional) - Icono en la bandeja del sistema

- Requiere `pystray` + `Pillow` (fuera de la lista de dependencias: **pedir
  permiso**). Menú: Abrir, Bloquear, Estado. Si no se aprueba, se omite.

---

## 14. Fase 7 - Integración con todo

### Paso 7.1 - `run.cmd run` con fichero de proyecto

- En cada proyecto, un fichero **sin secretos** `.cofre-env.json`:
  ```json
  {"TAVILY_API_KEY": "cofre://TAVILY_API_KEY",
   "GITHUB_TOKEN": "cofre://GITHUB_TOKEN@app",
   "DB_USER": "cofre://POSTGRES_LOCAL#username"}
  ```
  (`#campo` toma un campo distinto del valor; `@app` = token de GitHub App de
  1 hora, paso 5.4).
- `run.cmd run -- npm start` busca `.cofre-env.json` en la carpeta actual y
  hacia arriba, resuelve cada referencia (respetando políticas y confirmación),
  y lanza el comando con esas variables. Es la evolución de `exec --name`.
- `run.cmd run --check` dice qué faltaría, sin revelar (como `check`).
- **Commit:** `feat: run con referencias cofre:// por proyecto`

### Paso 7.2 - Ayudante de credenciales de git

- Script `git-credential-cofre.cmd` que llama a `python -m cofre.git_helper`.
- Protocolo de git: lee `protocol=`, `host=` por stdin; para `get`, si hay una
  entrada con `urls` que coincide con el host y tipo token/contraseña, responde
  `username=...` y `password=...`. Para `store` y `erase`: no hacer nada (COFRE
  no aprende solo).
- Configuración (la hace el usuario):
  `git config --global credential.helper "C:/Users/Sammi/AI/cofre/git-credential-cofre.cmd"`.
- Con el cofre cerrado: no responde nada (git pedirá la contraseña como siempre).
- **Commit:** `feat: ayudante de credenciales para git`

### Paso 7.3 - Harness de IA (PI, Hermes, LLM locales)

- Mantener lo ya diseñado en [[COFRE-INTEGRACION-2026-11-13]]: `exec`/`run`
  para inyectar y `check` para comprobar sin revelar.
- Añadir `run.cmd describe` → JSON con nombres, tipos, proveedor y estado de
  salud (nunca valores) para que un agente sepa qué hay disponible.
- **No** se crea un servidor que entregue valores a agentes. Si en el futuro
  hiciera falta, se construye solo con las cuatro reglas de
  [[COFRE-INTEGRACION-2026-11-13]] §3 y confirmación por petición.
- **Commit:** `feat: describe para agentes, sin valores`

### Paso 7.4 - Funciones de PowerShell

- `tools/cofre.ps1` con funciones `cofre`, `cofre-run`, `cofre-copy NOMBRE`
  (copia sin imprimir) que el usuario puede cargar en su `$PROFILE`.
- **Commit:** `feat: funciones de PowerShell`

---

## 15. Fase 8 - Calidad, recuperación y documentación

### Paso 8.1 - Batería completa y comprobación única

- `tools/check_all.py` ejecuta, en orden y con resumen final:
  pruebas unitarias, `gui --selftest`, `layout_check`, `theme_check`,
  `log verify` sobre un cofre temporal, `scan` del propio repo (que no haya
  secretos de prueba con pinta real).
- **Commit:** `test: comprobacion unica de calidad`

### Paso 8.2 - Versión y registro de cambios

- `cofre/__init__.py`: `__version__ = "2.0.0"`; `run.cmd --version`.
- `CHANGELOG.md` en el repo con una línea por commit relevante.
- **Commit:** `chore: version 2.0.0 y changelog`

### Paso 8.3 - Simulacro de desastre (lo hace el USUARIO, guiado)

Documento `COFRE-RECUPERACION.md` en la carpeta de documentación con este
simulacro, y el usuario lo ejecuta **una vez** con una copia del cofre:

1. Copiar `cofre.json` a una carpeta de prueba.
2. Sin pendrives conectados, abrir esa copia con el **código de recuperación**.
3. Añadir un pendrive nuevo a la copia.
4. Verificar que se leen 3 secretos al azar.
5. Borrar la carpeta de prueba.

Si falla cualquier paso, el código de recuperación no es válido: crear otro.

### Paso 8.4 - Documentación de usuario

Actualizar o crear en la carpeta de documentación:

- `COFRE-GUIA-USO-<fecha>.md` (sustituye a la de 2026-11-13).
- `COFRE-ROTACION.md`: cómo dar de alta un token de Cloudflare y de GitHub
  correctamente, cómo rotar, qué hace el pánico.
- `COFRE-NAVEGADOR.md`: instalación de la extensión, emparejamiento, sitios.
- `COFRE-AMENAZAS.md`: la sección 3 de este plan, revisada con lo implementado.

### Paso 8.5 (opcional) - Ejecutable con PyInstaller

- Solo si el usuario aprueba instalar PyInstaller. Ventajas: acceso directo sin
  consola, y host de mensajería nativa como `.exe` si la sonda 4.0 falló con
  `.bat`.

---

## 16. Fase 9 (opcional) - Llave FIDO2 por la API WebAuthn de Windows

- **Por qué volver a mirarlo:** en Windows 10/11 los programas sin privilegios
  de administrador **no** pueden abrir directamente el HID de una llave FIDO;
  deben usar la API WebAuthn del sistema. Eso encaja con el
  `ERROR_ACCESS_DENIED` documentado el 2026-11-08: no indica necesariamente que
  la llave no sirva, sino que se intentó por la vía bloqueada.
- **Sonda** `tools/webauthn_win_probe.py` con `python-fido2` (ya usado en la
  carpeta `_probe-fido`): usar el cliente de Windows de la librería
  (`fido2.client.windows`, comprobar el nombre exacto en la versión instalada)
  para `make_credential` con la extensión `hmac-secret`/`prf` y luego
  `get_assertion` con una sal fija dos veces: si devuelve **el mismo** secreto de
  32 bytes las dos veces, la llave sirve como gate.
- **Si funciona:** nuevo tipo de slot `fido2` en v2 (material = salida de
  `hmac-secret` con una sal guardada en el slot). Se añade como llave
  **adicional**, nunca como única.
- **Si no:** cerrar el tema definitivamente en [[COFRE]].

---

## 17. Lo que NO se va a hacer

| Idea | Por qué no |
|---|---|
| Exportar a `HKCU\Environment` | Deja los secretos en claro y persistentes; el pendrive deja de autorizar nada. Alternativa: `run` con `.cofre-env.json` (7.1) |
| Ficheros `.env` con valores | Mismo motivo; se filtran en commits y copias. Alternativa: 7.1 |
| Sincronizar el cofre en la nube "por comodidad" | Se puede exportar una copia cifrada (1.7), pero nunca junto a una llave |
| Guardar el TOTP (códigos 2FA) junto a la contraseña | Convierte dos factores en uno. Si el usuario lo pide explícitamente, se hace con una advertencia y tipo separado (decisión D6) |
| Capturar lo que se teclea en las webs | Riesgo y complejidad; alta manual desde el popup (4.8) |
| Interfaz web local | Más superficie de ataque que Tkinter |
| Autorrellenar al cargar la página | Siempre requiere un gesto del usuario (clic o atajo) |
| "Recordar el pendrive" | Rompe el modelo |

---

## 18. Decisiones abiertas para el usuario

El LLM ejecutor **no** decide esto. Si un paso depende de una decisión sin
respuesta, para y pregunta.

| # | Decisión | Opción recomendada | Afecta a |
|---|---|---|---|
| D1 | ¿Qué proveedores rotar primero? | Cloudflare y GitHub; el resto como genéricos | F5 |
| D2 | ¿PIN obligatorio (usb-pin) por defecto en v2? | Sí para el pendrive principal; protege si te roban el pendrive | F1 |
| D3 | Puente: ¿mensajería nativa o TCP con token? | Según la sonda 4.0 | F4 |
| D4 | GitHub: ¿crear una GitHub App propia? | Sí, para todo lo automatizado | 5.4 |
| D5 | ¿Instalar PyNaCl (para GitHub Actions)? | Sí, si se van a desplegar secretos en Actions | 5.6 |
| D6 | ¿Guardar TOTP? | No | 17 |
| D7 | ¿Bandeja del sistema (pystray)? | Opcional | 6.10 |
| D8 | ¿Dónde guardar la copia cifrada exportada? | Disco externo distinto de los pendrives | 1.7 |
| D9 | ¿Qué LLM local ejecuta el plan y con qué contexto? | Si el contexto es < 16k tokens, dividir aún más los pasos de las fases 1 y 5 | Todo |

---

## 19. Apéndices

### 19.1 Plantilla de paso (para pasos que el LLM tenga que añadir)

```
### Paso X.Y - Titulo en imperativo
- Objetivo: una frase.
- Por qué: una o dos frases.
- Depende de: pasos previos.
- Archivos: crear ... / modificar ... (funciones concretas)
- Instrucciones: lista numerada, una acción por línea.
- Prueba: comandos exactos y resultado esperado.
- Hecho cuando: lista de comprobaciones.
- Commit: tipo(ámbito): mensaje
- No hagas: lo que sería tentador y está prohibido.
```

### 19.2 Formato de commit

```
tipo(ambito): resumen en minusculas y en espanol

Paso X.Y del plan COFRE-PLAN-PRO-2026-11-13.
Que cambia y por que, en 1-3 lineas.
Pruebas: python -m unittest discover -s tests -> N ok
```
Tipos: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`.

### 19.3 Plantilla de registro en `PLAN-PRO-PROGRESO.md`

```
### 2026-11-20 10:42 - Paso 0.4.a
- Commit: abc1234
- Pruebas: 14 ok, 0 fallos
- Notas: (lo que el siguiente LLM debe saber)
```

### 19.4 Glosario

| Término | Significado |
|---|---|
| K / clave maestra | 32 bytes aleatorios que cifran todo. Nunca se escribe en claro |
| KEK | Clave que envuelve (cifra) a K. Una por slot |
| Slot / ranura | Una forma de abrir el cofre: un pendrive concreto o el código de papel |
| AAD | Datos que no se cifran pero quedan "firmados" con el cifrado; si cambian, descifrar falla |
| HKDF | Función para sacar varias claves distintas de una sola (K) |
| scrypt | Función lenta para convertir un secreto (pendrive + PIN) en una clave |
| HMAC | Firma con clave; sirve para detectar cambios y para huellas |
| Huella (fingerprint) | HMAC del valor; permite reconocer un secreto sin guardarlo en claro |
| Consumidor | Sitio donde está desplegado un secreto (GitHub Actions, un Worker…) |
| Rotar | Sustituir una credencial por otra nueva y revocar la vieja |
| Revocar | Invalidar una credencial en el proveedor |
| Honeytoken / señuelo | Credencial falsa que avisa si alguien la usa |
| rekey | Cambiar K y re-cifrar todo |

### 19.5 Dependencias permitidas

| Paquete | Para qué | Estado |
|---|---|---|
| `cryptography` | Todo el cifrado, JWT RS256 | Ya en uso |
| (stdlib) `urllib`, `json`, `hmac`, `hashlib`, `secrets`, `unittest`, `tkinter`, `ctypes` | Resto | Incluido en Python |
| `pynacl` | Cifrar secretos para GitHub Actions (5.6) | Pedir aprobación (D5) |
| `fido2` | Solo Fase 9 | Ya en `_probe-fido` |
| `pystray`, `Pillow` | Solo 6.10 | Pedir aprobación (D7) |
| `pyinstaller` | Solo 8.5 | Pedir aprobación |

Cualquier otro paquete: **preguntar**.

### 19.6 Referencias de API usadas en el plan (comprobadas el 2026-11-13)

**Cloudflare** (base `https://api.cloudflare.com/client/v4`, cabecera
`Authorization: Bearer <token>`):

| Acción | Método y ruta |
|---|---|
| Verificar token | `GET /user/tokens/verify` |
| Detalle de token | `GET /user/tokens/{token_id}` |
| Crear token | `POST /user/tokens` |
| Borrar token | `DELETE /user/tokens/{token_id}` |
| Roll (nuevo valor) token de usuario | `PUT /user/tokens/{token_id}/value` (cuerpo `{}`) |
| Roll token de cuenta | `PUT /accounts/{account_id}/tokens/{token_id}/value` (cuerpo `{}`) |
| Secretos de Workers | **Consultar la documentación oficial antes de usar** |

**GitHub** (base `https://api.github.com`, cabeceras
`Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2026-03-10`):

| Acción | Método y ruta | Notas |
|---|---|---|
| Verificar token | `GET /user` | 200 = válido |
| Revocar credenciales expuestas | `POST /credentials/revoke` | **Sin** autenticación (autenticada da 403); hasta 1000 por llamada; acepta `ghp_`, `github_pat_`, `gho_`, `ghu_`, `ghr_` |
| Token de instalación de GitHub App | `POST /app/installations/{installation_id}/access_tokens` | Autenticación con JWT de la App; caduca a la hora |
| Clave pública de secretos del repo | `GET /repos/{owner}/{repo}/actions/secrets/public-key` | |
| Crear/actualizar secreto del repo | `PUT /repos/{owner}/{repo}/actions/secrets/{secret_name}` | Valor cifrado con caja sellada de libsodium + `key_id` |

**Chrome, mensajería nativa:** manifiesto del host con `name`, `description`,
`path` (en Windows puede ser relativo al manifiesto), `type: "stdio"`,
`allowed_origins` (sin comodines). Registro en
`HKCU\Software\Google\Chrome\NativeMessagingHosts\<nombre>`. Mensajes: 4 bytes
de longitud (orden nativo) + JSON UTF-8. Nada por stdout salvo mensajes.

Si cualquier respuesta real difiere de esta tabla: **para y anótalo**.
