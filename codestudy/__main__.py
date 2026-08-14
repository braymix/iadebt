"""Permette `python -m codestudy ...` oltre allo script `codestudy`.

Utile quando lo script console-script non e' nel PATH (es. install con sudo
sul python di sistema): `python3 -m codestudy version`.
"""

from .cli import app

if __name__ == "__main__":
    app()
