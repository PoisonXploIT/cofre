#!/usr/bin/env python
"""Generar las wordlists del generador 'human' del cofre.

Guarda cofre/data/wordlist_en.txt y cofre/data/wordlist_es.txt. Son datos que
el generador necesita para funcionar, no documentacion.

Uso:
  python tools/build_wordlist.py --n 2000

Fuente: dwyl/english-words (words_alpha.txt), cruce de dos listas:
  - la base de palabras
  - el ranking de frecuencia real, si wordfreq esta instalado
Si no hay red o wordfreq falta, se usa un filtro por longitud (peor calidad).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
OUT_DIR = Path(__file__).resolve().parent.parent / "cofre" / "data"

STOP = {
    "the", "and", "for", "that", "with", "this", "from", "have", "you", "not",
    "are", "was", "their", "which", "will", "when", "what", "just", "than",
    "them", "there", "these", "those", "into", "some", "most", "like", "also",
    "make", "know", "take", "see", "come", "could", "want", "look", "give",
    "work", "find", "years", "more", "time", "very", "even", "thing", "many",
    "then", "been", "say", "does", "made", "said", "about", "would", "there",
    "their", "after", "because", "where", "while", "before", "against", "between",
    "your", "hers", "his", "her", "him", "they", "she", "he", "its", "our",
}


def download(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "cofre-wordlist"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="replace")


def pick(words: list[str], lang: str, n: int) -> list[str]:
    try:
        from wordfreq import zipf_frequency
        scored = [(zipf_frequency(w, lang), w) for w in words]
        scored.sort(key=lambda t: -t[0])
    except ImportError:
        print("aviso: wordfreq no esta instalado; orden por longitud", file=sys.stderr)
        scored = [(10 - abs(len(w) - 6), w) for w in words]

    seen = set()
    out = []
    for score, w in scored:
        if not re.fullmatch(r"[a-z]+", w):     # solo ASCII: compatible con todo
            continue
        if not 4 <= len(w) <= 9:
            continue
        if w in STOP or w in seen:
            continue
        if lang == "en" and score < 3.5:
            continue
        if lang == "es" and score < 3.0:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    args = ap.parse_args()

    try:
        raw = download(RAW)
    except Exception as exc:
        print(f"no se pudo descargar la base ({exc}). El generador seguira usando "
              "el fallback silabico.", file=sys.stderr)
        return 1

    words = raw.split()
    print(f"base: {len(words)} palabras")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for lang in ("en", "es"):
        wl = pick(words, lang, args.n)
        path = OUT_DIR / f"wordlist_{lang}.txt"
        path.write_text("\n".join(wl) + "\n", encoding="utf-8")
        bits = math.log2(len(wl)) if wl else 0
        print(f"{path}: {len(wl)} palabras, {bits:.1f} bits por palabra, "
              f"6 palabras = {6*bits:.0f} bits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
