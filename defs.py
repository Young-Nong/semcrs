"""
defs.py — index C function definitions in the CP source.

The original CRS used universal-ctags (`ctags --fields=+ne`) to locate every
function's file/start/end so it could slice code for the LLM. This keeps that
path (uses the `ctags` binary if it's on PATH) but adds a dependency-free
regex+brace-matching fallback so the demo runs anywhere without installing
ctags.
"""
import os
import re
import shutil
import subprocess

# start-of-line: optional return type/qualifiers, a name, (args), optional
# newline, then an opening brace. Excludes control keywords.
_DEF_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_ \t\*]*?)\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{",
    re.MULTILINE,
)
_KEYWORDS = {"if", "for", "while", "switch", "do", "return", "sizeof", "else"}


def _brace_end(text: str, open_idx: int) -> int:
    """Return the index just past the matching close brace of text[open_idx]=='{'."""
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _index_regex(src_root: str) -> dict:
    index = {}
    for dirpath, _, files in os.walk(src_root):
        if ".git" in dirpath:
            continue
        for fn in files:
            if not fn.endswith((".c", ".cc", ".cpp", ".h")):
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in _DEF_RE.finditer(text):
                name = m.group(2)
                if name in _KEYWORDS:
                    continue
                brace = text.index("{", m.start())
                end = _brace_end(text, brace)
                start_line = text.count("\n", 0, m.start()) + 1
                end_line = text.count("\n", 0, end) + 1
                index[name] = {
                    "path": path,
                    "start": start_line,
                    "end": end_line,
                    "code": text[m.start():end],
                }
    return index


def _index_ctags(src_root: str) -> dict:
    out = subprocess.run(
        ["ctags", "--fields=+ne", "-o", "-", "--sort=no", "-R", src_root],
        capture_output=True, text=True,
    ).stdout
    index = {}
    for line in out.splitlines():
        if line.startswith("!") or "\tf\t" not in ("\t" + line) and "\tf" not in line:
            pass
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, path = parts[0], parts[1]
        start = end = -1
        for p in parts:
            if p.startswith("line:"):
                start = int(p.split(":")[1])
            if p.startswith("end:"):
                end = int(p.split(":")[1])
        if start == -1 or end == -1:
            continue
        try:
            lines = open(path, encoding="utf-8", errors="ignore").readlines()
        except OSError:
            continue
        index[name] = {
            "path": path, "start": start, "end": end,
            "code": "".join(lines[start - 1:end]),
        }
    return index


def index_functions(src_root: str) -> dict:
    """name -> {path, start, end, code}. Prefers ctags; falls back to regex."""
    if shutil.which("ctags"):
        try:
            idx = _index_ctags(src_root)
            if idx:
                return idx
        except Exception:
            pass
    return _index_regex(src_root)


if __name__ == "__main__":
    import sys, json
    root = sys.argv[1] if len(sys.argv) > 1 else \
        "../asc-crs-buffalo/cp_root/mock-cp/src"
    idx = index_functions(root)
    print("engine:", "ctags" if shutil.which("ctags") else "regex-fallback")
    for k, v in idx.items():
        print(f"  {k:24s} {v['path']}:{v['start']}-{v['end']}")
