"""COFRE - tapar valores en la salida de un programa (D20, 2026-11-19).

Con `COFRE_AGENT=1`, `exec` y `run` no pueden dejar que el programa hijo imprima el
valor inyectado: el agente lo leería. Aquí se sustituye cada forma reconocible del
valor por `[REDACTADO]`.

Formas que se tapan (las que salen por descuido):

  - el valor tal cual;
  - base64 (con y sin relleno), base64 url-safe;
  - hexadecimal en minúsculas y mayúsculas;
  - codificado como URL (`quote`), también con `quote_plus`;
  - con comillas de JSON (`json.dumps`).

No frena a un agente que quiera esconderlo de verdad (puede ofuscar a mano); frena
la fuga por descuido, que es la probable: un `print(os.environ)`, un `env`, un log
del programa.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse

MARCA = "[REDACTADO]"


def variantes(valor: str) -> list[str]:
    """Las formas del valor que hay que tapar, de la más larga a la más corta."""
    if not valor:
        return []
    crudo = valor.encode("utf-8")
    _signos = "".join(chr(b) if (48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122)
                      else "%%%02X" % b for b in crudo)
    formas = {
        valor,
        base64.b64encode(crudo).decode("ascii"),
        base64.b64encode(crudo).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("="),
        crudo.hex(),
        crudo.hex().upper(),
        urllib.parse.quote(valor, safe=""),
        urllib.parse.quote_plus(valor, safe=""),
        # sobre-codificado: cada byte como %XX (lo hacen algunas librerías)
        "".join("%%%02X" % b for b in crudo),
        "".join("%%%02x" % b for b in crudo),
        # solo los signos ('-' y '_' incluidos), con el %XX en mayuscula o minuscula
        _signos,
        re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), _signos),
        json.dumps(valor)[1:-1],
    }
    return sorted((f for f in formas if f and f != MARCA), key=len, reverse=True)


def redactar(texto: str, valores) -> str:
    """Sustituye cada forma de cada valor por la marca.

    `valores` puede ser un diccionario {nombre: valor} o una lista de valores.
    """
    if not texto:
        return texto
    if isinstance(valores, dict):
        lista = list(valores.values())
    else:
        lista = list(valores)
    for valor in lista:
        for forma in variantes(str(valor)):
            if forma in texto:
                texto = texto.replace(forma, MARCA)
    return texto


def comando_visible(comando) -> str:
    """El comando en una línea, para enseñarlo en el diálogo de confirmación."""
    if isinstance(comando, (list, tuple)):
        return " ".join(str(p) for p in comando)
    return str(comando)
