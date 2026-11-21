# COFRE

**Bóveda local de secretos con llave física y frase.** Para Windows. Guarda tokens, API
keys, certificados y contraseñas cifrados en tu equipo, y para abrirlos hace falta un
pendrive **y** una frase que solo sabes tú. Sin servidores, sin nube, sin cuenta.

`Python 3.11+` · `Windows 10/11` · `MIT` · `396 pruebas` · `24 sondas`

> **English (short).** COFRE is a local-first secrets vault for Windows. Secrets are
> encrypted with AES-256-GCM under a master key that never touches disk: it is wrapped
> in several *slots*, one per hardware key (a USB stick holding 32 random bytes, plus a
> passphrase) and one for a 25-word paper recovery code. Optional PIN-protected slots,
> HMAC-chained audit log, browser autofill over a named pipe (no open ports), a git
> credential helper, credential rotation with a journal, a panic button and a leak
> scanner. Pure Python + Tkinter, no cloud, no account.

---

## Índice

- [Qué es (y qué no es)](#qué-es-y-qué-no-es)
- [Cómo funciona](#cómo-funciona)
- [Qué protege y qué no](#qué-protege-y-qué-no)
- [Características](#características)
- [Instalación](#instalación)
- [Primer uso](#primer-uso)
- [Uso diario](#uso-diario)
- [Mantenimiento y copias](#mantenimiento-y-copias)
- [Comprobaciones](#comprobaciones)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Limitaciones conocidas](#limitaciones-conocidas)
- [Licencia](#licencia)

## Qué es (y qué no es)

Es un gestor de secretos **de escritorio y de un solo usuario**, pensado para quien
quiere que la llave sea algo físico y no una contraseña maestra guardada en un fichero.
La ventana es Tkinter; no hay servicio, ni puerto abierto obligatorio, ni base de datos.

No es un gestor de contraseñas multiusuario, ni un HSM, ni un producto auditado. Es un
proyecto personal, con pruebas, que hace explícito su modelo de amenazas.

## Cómo funciona

```
cofre.json  (formato 2, el único fichero con datos)
│
├── ranura «usb»  E:   abre con   COFRE.KEY (32 bytes)  +  tu frase   ─┐
├── ranura «usb»  F:   abre con   COFRE.KEY (32 bytes)  +  tu frase   ─┼──▶  clave maestra K
└── ranura «recovery»  abre con   las 25 palabras del papel            ─┘         │
                                                                                 │  AES-256-GCM
                                                              índice cifrado + secretos
```

- **Clave maestra K**: 32 bytes al azar. **No está en ningún fichero.** Solo existe en
  memoria mientras el cofre está abierto.
- **Ranuras**: cada llave guarda K envuelta a su manera. De *material* de cada ranura
  sale una clave derivada con **scrypt** (N=2¹⁵, r=8, p=1) sobre su propia sal; con ella
  se descifra el envoltorio AES-256-GCM de K. Añadir o retirar una llave es añadir o
  retirar una ranura: no se re-cifran los datos.
- **Llave del pendrive**: `COFRE.KEY`, 32 bytes al azar, distinta en cada pendrive. No se
  deriva del hardware: se guarda. El serial del volumen tiene que estar registrado, así
  que copiar el fichero a otro pendrive no sirve.
- **Frase (PIN)**: opcional por ranura y recomendada. La ranura pasa a necesitar llave
  **y** frase. La frase no se guarda en ningún sitio: la ranura solo recuerda que pide
  frase.
- **Código de recuperación**: 24 palabras al azar de una lista de 2000 (≈11 bits por
  palabra) más una de control que detecta erratas, ≈263 bits. Solo en papel. Sirve para
  abrir sin ningún pendrive; no se usa en el día a día.
- **Índice**: todo lo demás (nombres, metadatos, dominios asignados, política, salud,
  caducidades, diario de rotación) va dentro del mismo bloque cifrado. El fichero no
  revela ni los nombres de tus secretos.

## Qué protege y qué no

| Escenario | Resultado |
|---|---|
| Te roban el portátil con el cofre dentro | No se abre: falta la llave física |
| Te roban un pendrive, sin la frase | No se abre: la ranura pide frase |
| Alguien copia `cofre.json` a otro sitio | No se abre: falta una llave |
| Copias `COFRE.KEY` a otro pendrive | No sirve: el serial no está registrado |
| Pierdes un pendrive | Abres con el otro, o con el papel |
| Pierdes la frase | No hay recuperación de la frase: te quedan el papel o una ranura sin frase |
| Pierdes los pendrives **y** el papel | El cofre no se abre. No hay puerta trasera |
| Malware en tu equipo con el cofre abierto | **Puede leer lo que se descifre.** Ahí no llega el cifrado |
| Alguien que te conoce adivina tu frase | Por eso: 5-6 palabras al azar, no una frase inventada |

## Características

**Llaves y apertura**
- Formato v2 con ranuras por pendrive y sal propia en cada una; migración desde v1 con el
  histórico antiguo en solo lectura y anclado por hash.
- PIN por ranura (posesión + conocimiento), con verificación al crearla y restauración si
  algo falla.
- Código de recuperación de 25 palabras, comprobable desde la ventana (`Probar código`) y
  regenerable sin necesitar el anterior.
- Ventana con pantalla de bloqueo, campo de frase y avisos que dicen la causa real.

**Sesión y políticas**
- Bloqueo por inactividad (10 min), tope de sesión (8 h), detección de suspensión, bloqueo
  de Windows (Win+L) y bloqueo automático al retirar el pendrive.
- Política por secreto y canal: `browser`, `exec`, `clipboard`, `reveal`, `git`.
- Confirmación en pantalla con **Denegar por defecto**, 20 s de plazo, «Permitir una vez»
  y «Permitir 5 minutos» por host, con retardo para que un clic heredado no autorice nada.
- Permisos temporales a la vista, con cuenta atrás y botón para retirarlos.

**Auditoría**
- Registro encadenado con HMAC y *checkpoint* que se sella en cada evento; los eventos
  privilegiados van firmados.
- Los cambios de clave no re-firman el pasado: cierran el tramo con la clave vieja, lo
  archivan en solo lectura y el nuevo lo ancla por SHA-256.
- Reglas de alerta: ráfaga, señuelo (honeytoken), fallos de apertura, hora rara, puente,
  log/checkpoint, credencial sin revocar, rotación interrumpida.

**Navegador y git**
- Mensajería nativa + **tubería con nombre** con validación de cliente (binario, usuario,
  PID): sin puertos abiertos. TCP en 127.0.0.1 solo como respaldo opcional.
- Relleno únicamente en los dominios asignados a **ese** secreto; señuelos que nunca se
  entregan.
- Ayudante de credenciales de git: no abre el cofre, pregunta a la ventana por la tubería
  y registra `git:<host>` con el pid. Con la ventana cerrada no devuelve nada.

**Ciclo de vida**
- Proveedores Cloudflare y GitHub; proveedor genérico configurable y `meta --verify` para
  cualquier otra API.
- Rotación con diario cifrado, historial de versiones, credencial vieja pendiente de
  revocar, aviso a los 7 días y `resume` para deshacer o continuar.
- Salud de cada credencial con verificación real, calendario de caducidades sin nombres y
  `due --notify`.
- Botón de pánico (`panic --dry-run` para ver el plan) y `rekey` de la clave maestra.

**Extras**
- `scan`: escáner de fugas por huellas HMAC (dice *dónde* está un secreto tuyo, sin
  mostrarlo) y gancho de `pre-commit`.
- `run` y `exec`: inyectar secretos en un proceso concreto, sin escribir ficheros.
- Candado para agentes (`COFRE_AGENT=1`): los comandos que muestran valores se niegan.

## Instalación

Solo Windows (usa la API de Windows para portapapeles, tuberías, seriales de volumen y
bloqueo de sesión). Python 3.11 o superior; probado con 3.12.

```bat
git clone https://github.com/PoisonXploIT/cofre.git
cd cofre
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Dependencias: `cryptography` y `pynacl`. `fido2` es opcional (el *gate* FIDO2 está
descartado: el driver de esta máquina no deja pasar CTAP2).

Los datos **no** viven en el repo: por defecto en `%LOCALAPPDATA%\cofre\vault`, o donde
diga la variable `COFRE_VAULT`.

## Primer uso

1. Enchufa un pendrive y abre la ventana:

   ```bat
   .\run.cmd gui
   ```

   Si el cofre no existe, aparece el panel **Puesta en marcha**. El asistente hace tres
   cosas: crea `COFRE.KEY` en el pendrive, crea el cofre y genera el **código de
   recuperación de 25 palabras**.

2. **Apunta las 25 palabras en papel** antes de cerrar la ventana. Se muestran una sola
   vez y no se guardan en ningún fichero. Guárdalas en un sitio distinto del portátil.

3. Activa la frase del pendrive: **Llaves y recuperación → Poner PIN al pendrive**
   (o `.\run.cmd stick-pin --stick E:\COFRE.KEY`). A partir de ahí:

   ```bat
   .\run.cmd gui --gate usb-pin
   ```

4. Repite con un segundo pendrive como reserva (otra llave, misma frase si quieres).

Por consola, las mismas piezas: `stick-init E:\COFRE.KEY` crea la llave y registra el
serial; `init` crea el cofre; `stick-add-v2` añade la ranura de un pendrive nuevo.

## Uso diario

| Quiero | Comando |
|---|---|
| Abrir la ventana | `.\run.cmd gui --gate usb-pin` (pide la frase) |
| Ver los nombres (sin valores) | `.\run.cmd list --gate usb-pin` |
| Guardar un secreto | `.\run.cmd add NOMBRE --gate usb-pin` (pide el valor a ciegas) |
| Sacar un valor | `.\run.cmd get NOMBRE --gate usb-pin` |
| Inyectarlo en un proceso | `.\run.cmd run --gate usb-pin -- python script.py` |
| Una sola variable | `.\run.cmd exec --gate usb-pin --name TOKEN -- programa` |
| Rotar una credencial | `.\run.cmd rotate NOMBRE --dry-run` y luego `--si` |
| Comprobar el registro | `.\run.cmd log verify --gate usb-pin` |
| Abrir sin pendrive | `.\run.cmd --recovery get NOMBRE` (pide las 25 palabras) |
| Buscar fugas en un repo | `.\run.cmd scan --repo C:\ruta` |

En PowerShell, todo lo que empieza por `run.cmd` se escribe con `.\` delante. La frase se
puede pasar en la variable `COFRE_PIN` para uso no interactivo: no se escribe en ningún
fichero, y `sesion` la pide una sola vez y solo se la da a sus procesos hijos.

La ventana tiene además: paleta (`Ctrl+K`), copiar (`Ctrl+C`, el portapapeles se vacía a
los 30 s), ver el valor con auto-ocultación a los 15 s, relleno en el navegador
(`Ctrl+Shift+L`), permiso temporal para git, salud y caducidades, registro firmado y una
guía paso a paso dentro de la propia aplicación (botón **Guía**).

## Mantenimiento y copias

Una vez al mes, con los dos pendrives y el disco de copias conectados:

```bat
.\run.cmd sesion --gate usb-pin
```

Pide la frase una vez y comprueba: discos y registro, `log verify`, que cada pendrive
abre, la tarea de Windows, el plan de pánico en seco y la copia de seguridad con
simulacro de restauración.

La copia son tres ficheros de `%LOCALAPPDATA%\cofre\vault`: `cofre.json`,
`.cofre-sticks.json` y `.cofre-salt` (en v2 la sal va en cada ranura; el fichero se
mantiene por compatibilidad). **Ninguno contiene tu frase.** Borra las copias viejas: una
copia hecha antes de cambiar el código de recuperación se abre con el código viejo.

Si algún día un secreto aparece en un proyecto, `scan` lo localiza por huella y el gancho
de `pre-commit` frena el commit antes de que salga.

## Comprobaciones

```bat
.venv\Scripts\python -m unittest discover -s tests    (396 pruebas)
.venv\Scripts\python tools\run_all_probes.py          (24 sondas obligatorias)
.venv\Scripts\python tools\check_all.py               (pruebas, selftest, layout, tema,
                                                       log en cofre temporal y escaneo)
```

Las sondas abren ventanas de verdad y miden la interfaz (geometría, foco, botones, capa de
bloqueo, permisos, tubería, servidor del navegador). Hay un trinquete sobre el catálogo de
textos: el número de cadenas pendientes de traducir solo baja, y subir exige justificarlo
por escrito en el propio commit.

## Estructura del repositorio

```
cofre/                 paquete principal
  cli.py               línea de comandos (todo pasa por aquí)
  gui.py + gui_*.py    ventana Tkinter, repartida en mixins
  lock_screen.py       pantalla de bloqueo (llaves, frase, avisos)
  crypto.py store.py   cifrado y almacén
  v2/                  formato 2: slots.py, vault.py, recovery.py, rekey.py, migrate.py
  audit.py alerts.py   registro encadenado y reglas de alerta
  policy.py session.py política por canal y sesión con plazos
  usb.py gate.py       llaves físicas, seriales y derivación
  pipe_server.py nmhost.py bridge_ops.py   tubería, mensajería nativa y despacho
  providers/           Cloudflare, GitHub, genérico
  panic.py rotation.py health.py schedule.py   ciclo de vida
  leak.py scan         escáner de fugas
  theme.py widgets.py  interfaz (tema, controles)
  sesion_fisica.py     comprobación completa con discos y copia
tests/                 396 pruebas, con cofres temporales
tools/                 sondas, verificadores y utilidades
extension/             extensión de navegador
nmhost/                host de mensajería nativa
assets/                icono
```

Sin dependencias de interfaz: Tkinter es de la biblioteca estándar. `cryptography` aporta
AES-GCM y scrypt; `pynacl` se usa donde hace falta.

## Decisiones de diseño

Están escritas y numeradas en la documentación del proyecto; las que más se notan:

| # | Decisión |
|---|---|
| D10 | Los dominios asignados van **dentro** del índice cifrado: el fichero no dice para qué sitio es cada secreto |
| D11 | Una llave de 32 bytes **distinta por pendrive**: revocar una no deja entrar a las demás |
| D17 | Sin empaquetar con PyInstaller: el `.bat` y `pythonw` bastan |
| D18 | El agente (modelo) hace todo lo posible; el usuario solo lo físicamente imposible |
| D19 | Nada se borra por contenido: ruta exacta, listar antes y permiso que nombre el fichero |
| D20 | Con `COFRE_AGENT=1`, los comandos que muestran valores se niegan y `exec`/`run` piden confirmación |
| D22 | PIN en el pendrive: sin la frase, la llave sola no abre |

## Limitaciones conocidas

- **Solo Windows.** El portapapeles, las tuberías, los seriales de volumen y el bloqueo de
  sesión se apoyan en la API de Windows.
- **Un usuario por equipo.** No hay multiusuario ni roles.
- **El malware con el cofre abierto gana.** El cifrado protege el fichero en reposo y los
  respaldos, no un proceso que ya corre en tu sesión.
- **La frase no se puede recuperar.** No hay preguntas de seguridad ni correo: si se
  olvida, quedan el otro pendrive o el papel.
- **No auditado.** Tiene pruebas, no una auditoría externa. Si lo usas para algo crítico,
  revísalo antes.
- **El *gate* FIDO2 está descartado.** Está el código y la evidencia: en la máquina donde se
  desarrolló, el driver no deja pasar tráfico CTAP2.
- Las sondas de navegador necesitan Chrome/Edge con CDP y `puppeteer-core`, y no entran en
  la batería obligatoria.

## Licencia

MIT. Ver [LICENSE](LICENSE).

Hecho por [Sammi De Blas](https://sammideblas.com). Si encuentras algo, abre un *issue*.
