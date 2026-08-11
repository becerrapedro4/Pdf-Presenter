"""Chequeo de sintaxis de los scripts del proyecto (corre en CI sin dependencias)."""
import ast
import pathlib


def test_sintaxis():
    root = pathlib.Path(__file__).parent
    for name in ("PDFPresenter5.py", "PDFPresenter6.py"):
        ast.parse((root / name).read_text(encoding="utf-8"), filename=name)
