@echo off
if not exist .venv\Scripts\python.exe (
    python -m venv .venv
    .venv\Scripts\python -m pip install -q cryptography fido2
)
.venv\Scripts\python -m cofre.cli %*
