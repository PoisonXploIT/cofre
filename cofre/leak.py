"""COFRE - escáner de fugas (paso 3.4, hecho el 2026-11-18).

Busca si algún secreto del cofre está pegado en un fichero de tus proyectos. No
muestra el valor nunca: compara **huellas HMAC** de los candidatos con las de los
secretos, y solo dice nombre, fichero y línea.

Por qué HMAC y no el valor en claro:

  - la clave de las huellas se deriva de la clave maestra del cofre, así que una
    huella no sirve para probar diccionarios contra otros cofres;
  - el valor no se compara como texto libre con el fichero: se comparan huellas, y
    del valor no queda copia en ningún sitio;
  - los candidatos se sacan por palabras (>= 8 caracteres de
    `[A-Za-z0-9_.+/:-]` sin separadores: de `CF_TOKEN=abc...` sale `abc...`). Un
    valor que no es una sola palabra (lleva espacios o `= : @`) y los de menos de 8
    caracteres se buscan como subcadena: no habría palabra que los aislara.

Lo que **no** hace: no decide si el fichero es tuyo o del sistema; escanea la
carpeta que le digas y salta `.git`, `.venv`, `node_modules`, `__pycache__`,
binarias y ficheros enormes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import subprocess
from pathlib import Path

MIN_TOKEN = 8
MAX_BYTES = 8 * 1024 * 1024      # un fichero mayor no se lee entero
TOKEN = re.compile(r"[A-Za-z0-9_\-\.\+/]{8,}")
SOLO_TOKEN = re.compile(r"^[A-Za-z0-9_\-\.\+/]{%d,}$" % MIN_TOKEN)

EXCLUIDOS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
             ".pytest_cache", "dist", "build", ".idea", ".vscode", "site-packages"}
BINARIAS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".7z", ".rar",
            ".gz", ".exe", ".dll", ".pyd", ".so", ".pyc", ".woff", ".woff2",
            ".ttf", ".mp3", ".mp4", ".mkv", ".webp", ".bmp", ".sqlite", ".db"}


def clave_de_huellas(master: bytes) -> bytes:
    """Subclave para las huellas: no se usa la maestra directamente."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"cofre/leak").derive(master)


def huella(clave: bytes, valor: str) -> bytes:
    return hmac.new(clave, valor.encode("utf-8"), hashlib.sha256).digest()


def huellas_de(clave: bytes, secretos: dict[str, str]) -> tuple[dict[bytes, str],
                                                               list[tuple[str, str]]]:
    """(huella -> nombre, valores cortos que no se pueden aislar como palabra)."""
    tabla: dict[bytes, str] = {}
    cortos: list[tuple[str, str]] = []
    for nombre, valor in secretos.items():
        if not valor:
            continue
        if not SOLO_TOKEN.match(valor):
            cortos.append((nombre, valor))
            continue
        tabla[huella(clave, valor)] = nombre
    return tabla, cortos


def _es_texto(datos: bytes) -> bool:
    if b"\x00" in datos[:4096]:
        return False
    try:
        datos[:4096].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def escanear_texto(texto: str, clave: bytes, tabla: dict[bytes, str],
                   cortos: list[tuple[str, str]]) -> list[tuple[int, str]]:
    """[(línea, nombre)] de cada coincidencia. El valor no se devuelve."""
    hallazgos: list[tuple[int, str]] = []
    for numero, linea in enumerate(texto.splitlines(), start=1):
        nombres: set[str] = set()
        for candidato in TOKEN.findall(linea):
            nombre = tabla.get(huella(clave, candidato))
            if nombre:
                nombres.add(nombre)
        for nombre, valor in cortos:
            if valor in linea:
                nombres.add(nombre)
        for nombre in sorted(nombres):
            hallazgos.append((numero, nombre))
    return hallazgos


def _ruta_valida(ruta: Path) -> bool:
    if any(parte in EXCLUIDOS for parte in ruta.parts):
        return False
    return ruta.suffix.lower() not in BINARIAS


def escanear_fichero(ruta: Path, clave: bytes, tabla: dict[bytes, str],
                     cortos: list[tuple[str, str]]) -> list[tuple[int, str]]:
    try:
        if ruta.stat().st_size > MAX_BYTES:
            return []
        datos = ruta.read_bytes()
    except OSError:
        return []
    if not _es_texto(datos):
        return []
    try:
        texto = datos.decode("utf-8", errors="replace")
    except Exception:                                  # noqa: BLE001
        return []
    return escanear_texto(texto, clave, tabla, cortos)


def escanear_carpeta(carpeta: Path, clave: bytes, tabla: dict[bytes, str],
                     cortos: list[tuple[str, str]]) -> list[tuple[Path, int, str]]:
    """Recorre la carpeta y devuelve [(ruta, línea, nombre)]."""
    salida: list[tuple[Path, int, str]] = []
    for raiz, dirs, ficheros in _recorrer(carpeta):
        dirs[:] = [d for d in dirs if d not in EXCLUIDOS]
        for nombre in sorted(ficheros):
            ruta = Path(raiz) / nombre
            if not _ruta_valida(ruta):
                continue
            for linea, secreto in escanear_fichero(ruta, clave, tabla, cortos):
                salida.append((ruta, linea, secreto))
    return salida


def _recorrer(carpeta: Path):
    return os.walk(carpeta)


def escenificado(repo: Path, ruta: str) -> bytes | None:
    """Contenido del fichero tal y como va en el commit (git show :ruta)."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), "show", f":{ruta}"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def ficheros_escenificados(repo: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only",
             "--diff-filter=ACMR"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def escanear_escenificados(repo: Path, clave: bytes, tabla: dict[bytes, str],
                           cortos: list[tuple[str, str]]) -> list[tuple[Path, int, str]]:
    """Lo que se va a commitear, no lo que hay en el disco."""
    salida: list[tuple[Path, int, str]] = []
    for rel in ficheros_escenificados(repo):
        datos = escenificado(repo, rel)
        if datos is None or not _es_texto(datos):
            continue
        texto = datos.decode("utf-8", errors="replace")
        for linea, secreto in escanear_texto(texto, clave, tabla, cortos):
            salida.append((Path(repo) / rel, linea, secreto))
    return salida
