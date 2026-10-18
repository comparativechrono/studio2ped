"""Write studio2ped_standalone.py: the package as one file that runs without installing it.

The script is the converter module followed by the command line, with their
imports gathered at the top. Run this from the repository's root whenever the
package changes:

    python tools/make_standalone.py

tests/test_standalone.py fails when the script is out of date.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "studio2ped"
OUTPUT = ROOT / "studio2ped_standalone.py"
MODULES = ("converter.py", "cli.py")   # in this order: the command line uses the converter

HEADER = '''#!/usr/bin/env python3
"""
studio2ped_standalone.py - Convert Pedigree Studio session JSON to PED/MPED files.

Standalone single-file script: studio2ped {version} in one file, so no
installation is required - it needs only Python 3.9+.

Usage:
    python studio2ped_standalone.py session.studio.json [--ids numbers|drawing|studio|text] [-o prefix] [-d dir]

This file is made from the package by tools/make_standalone.py: change the
package, not this file.
"""
'''


def version() -> str:
    text = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M).group(1)


def split_module(path: pathlib.Path):
    """A module's top-level imports (other than relative and __future__ ones),
    and its code after the docstring and imports."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports, start = [], 0
    for node in tree.body:
        docstring = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if not (isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__")):
                imports.append(ast.get_source_segment(source, node))
        elif not docstring:
            break
        start = node.end_lineno
    body = "".join(source.splitlines(keepends=True)[start:]).strip("\n")
    return imports, body


def build() -> str:
    imports, bodies = [], []
    for name in MODULES:
        found, body = split_module(PACKAGE / name)
        imports.extend(i for i in found if i not in imports)
        bodies.append(body)
    plain = sorted(i for i in imports if i.startswith("import "))
    froms = sorted(i for i in imports if i.startswith("from "))
    parts = [HEADER.format(version=version()), "from __future__ import annotations\n",
             "\n".join(plain + froms) + "\n", '__version__ = "{}"\n'.format(version())]
    return "\n".join(parts) + "\n" + "\n\n\n".join(bodies) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print("wrote", OUTPUT.relative_to(ROOT))
