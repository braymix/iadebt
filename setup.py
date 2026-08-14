"""Shim setuptools per compatibilita' con pip/setuptools datati.

I metadati canonici sono in pyproject.toml; qui li ripetiamo in modo esplicito
cosi' `pip install -e .` funziona anche con versioni vecchie di pip che
richiedono un build setuptools legacy (setup.py develop).
"""

from setuptools import setup, find_packages

setup(
    name="codestudy",
    version="0.1.0",
    description=(
        "Genera materiale di studio (flashcard, mappe Mermaid, note) dal tuo "
        "repository git per colmare il debito di comprensione del codice AI."
    ),
    python_requires=">=3.9",
    packages=find_packages(include=["codestudy*"]),
    include_package_data=True,
    package_data={"codestudy.stack": ["rules/*.yaml"]},
    install_requires=[
        "typer>=0.9",
        "PyYAML>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "codestudy=codestudy.cli:app",
        ],
    },
)
