"""Repair compact inline Python suites without altering executable AST.

Only transforms one-line compounds and multiple simple statements. Bail out if
any executable syntax tree changes. Intended solely for staged R6.3.1 source.
"""
from __future__ import annotations
import ast
import io
import sys
import tokenize
from pathlib import Path

COMPOUNDS = {"if", "elif", "else", "while", "for", "try", "except", "finally",
             "with", "def", "class", "async", "match", "case"}


def expand_compact_suites(source: str) -> str:
    expected = ast.dump(ast.parse(source), include_attributes=False)
    for _ in range(20):
        lines = source.splitlines(keepends=True)
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        first, colons, semicolons = {}, {}, {}
        depth = 0
        for token in tokens:
            row, column = token.start
            if token.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER, tokenize.STRING):
                first.setdefault(row, token.string)
            if token.type == tokenize.OP:
                if token.string in ("(", "[", "{"):
                    depth += 1
                elif token.string in (")", "]", "}"):
                    depth -= 1
                elif token.string == ":" and depth == 0:
                    colons.setdefault(row, []).append(column)
                elif token.string == ";" and depth == 0:
                    semicolons.setdefault(row, []).append(column)
        changed = 0
        for row in sorted(set(colons) | set(semicolons), reverse=True):
            if row > len(lines):
                continue
            line = lines[row - 1]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            stripped = line.lstrip(" \t")
            indent = line[:len(line) - len(stripped)]
            if row in colons and first.get(row) in COMPOUNDS:
                for column in reversed(colons[row]):
                    tail = line[column + 1:].strip(" \t\r\n")
                    if not tail or tail.startswith("#"):
                        continue
                    transformed = (line[:column + 1].rstrip() + "\n"
                                   + indent + "    " + line[column + 1:].lstrip(" \t"))
                    if line.endswith("\n") and not transformed.endswith("\n"):
                        transformed += "\n"
                    lines[row - 1] = transformed
                    changed += 1
                    break
            elif row in semicolons:
                columns = [c for c in semicolons[row] if c < len(line)]
                transformed = line
                for column in reversed(columns):
                    transformed = (transformed[:column].rstrip() + "\n"
                                   + indent + transformed[column + 1:].lstrip(" \t"))
                if columns:
                    lines[row - 1] = transformed
                    changed += len(columns)
        if not changed:
            break
        source = "".join(lines)
        if ast.dump(ast.parse(source), include_attributes=False) != expected:
            raise ValueError("Executable AST changed; refusing style repair")
    if ast.dump(ast.parse(source), include_attributes=False) != expected:
        raise ValueError("Executable AST changed")
    return source


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        path = Path(filename)
        before = path.read_text(encoding="utf-8")
        after = expand_compact_suites(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            print("Expanded inline suites:", path)
