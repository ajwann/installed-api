#!/usr/bin/env python3
"""installed-api: a stdio MCP server (stdlib only) answering API questions from installed code.

Python questions run in the project's own interpreter (.venv, venv, $VIRTUAL_ENV, poetry/pdm env,
else python3) via pyprobe.py. TypeScript/JavaScript questions read node_modules on disk.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

SERVER_NAME = "installed-api"
SERVER_VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent
PROBE = HERE / "pyprobe.py"
DEFAULT_PROTOCOL = "2025-06-18"


# ---------------------------------------------------------------- project + interpreter

def project_dir(arg: Optional[str]) -> Path:
    return Path(arg or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def find_python(project: Path) -> tuple[str, str]:
    """(interpreter, how it was found)"""
    for d in (project, *project.parents):
        for venv in (".venv", "venv", ".env", "env"):
            for exe in ("bin/python", "Scripts/python.exe"):
                p = d / venv / exe
                if p.exists():
                    return str(p), f"{(d / venv)}"
        if (d / ".git").exists():
            break
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and (Path(venv) / "bin" / "python").exists():
        return str(Path(venv) / "bin" / "python"), "$VIRTUAL_ENV"
    for tool, args in (("poetry", ["env", "info", "-e"]), ("pdm", ["info", "--python"])):
        if (project / "pyproject.toml").exists() and shutil.which(tool):
            try:
                r = subprocess.run([tool, *args], cwd=project, capture_output=True, text=True, timeout=10)
                exe = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
                if exe and Path(exe).exists():
                    return exe, f"{tool} environment"
            except (OSError, subprocess.TimeoutExpired, IndexError):
                pass
    return shutil.which("python3") or sys.executable, "python3 on PATH"


def probe(project: Path, req: dict, include_project: bool) -> dict:
    exe, how = find_python(project)
    if include_project:
        req["sys_path"] = [str(project / "src"), str(project)]
    try:
        r = subprocess.run([exe, "-I", str(PROBE), json.dumps(req)], cwd=project, capture_output=True,
                           text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"error": "the probe timed out after 60s (importing the module may hang or be slow)"}
    except OSError as e:
        return {"error": f"cannot run {exe}: {e}"}
    out = r.stdout.strip().splitlines()
    try:
        data = json.loads(out[-1]) if out else {"error": (r.stderr or "no output").strip()[-1500:]}
    except ValueError:
        data = {"error": "probe produced non-JSON output", "stdout": r.stdout[-1500:], "stderr": r.stderr[-1500:]}
    data["interpreter"] = f"{exe} ({how})"
    return data


# ---------------------------------------------------------------- node

def node_package_dir(project: Path, package: str) -> Optional[Path]:
    for d in (project, *project.parents):
        cand = d / "node_modules" / package
        if (cand / "package.json").exists():
            return cand
        if (d / ".git").exists() and d != project:
            break
    return None


def _types_entry(pkg_dir: Path, meta: dict) -> Optional[Path]:
    cands = []
    exp = meta.get("exports")
    if isinstance(exp, dict):
        dot = exp.get(".", exp)
        if isinstance(dot, dict):
            for key in ("types", "typings"):
                if isinstance(dot.get(key), str):
                    cands.append(dot[key])
            for cond in ("import", "require", "default"):
                sub = dot.get(cond)
                if isinstance(sub, dict) and isinstance(sub.get("types"), str):
                    cands.append(sub["types"])
    for key in ("types", "typings"):
        if isinstance(meta.get(key), str):
            cands.append(meta[key])
    main = meta.get("main") if isinstance(meta.get("main"), str) else "index.js"
    cands += [re.sub(r"\.(c|m)?js$", ".d.ts", main), "index.d.ts"]
    for c in cands:
        p = (pkg_dir / c).resolve()
        if p.is_file():
            return p
        if p.with_suffix(".d.ts").is_file():
            return p.with_suffix(".d.ts")
    return None


DECL_RE = r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?" \
          r"(?:function\*?|class|interface|type|const|let|var|enum|namespace|module)\s+{name}\b"


def _extract_block(lines: list[str], start: int, max_lines: int = 80) -> str:
    out, depth, seen_brace = [], 0, False
    for line in lines[start: start + max_lines]:
        out.append(line)
        depth += line.count("{") - line.count("}")
        seen_brace = seen_brace or "{" in line
        stripped = line.strip()
        if (seen_brace and depth <= 0) or (not seen_brace and stripped.endswith(";")):
            break
    # include JSDoc above the declaration
    doc, j = [], start - 1
    while j >= 0 and (lines[j].strip().startswith(("*", "/**", "*/")) or lines[j].strip() == ""):
        if lines[j].strip():
            doc.insert(0, lines[j])
        if lines[j].strip().startswith("/**"):
            break
        j -= 1
    return "\n".join(doc[-25:] + out)


def node_lookup(project: Path, package: str, symbol: Optional[str], max_files: int = 400) -> dict:
    pkg_dir = node_package_dir(project, package)
    types_pkg = None
    if not pkg_dir:
        return {"error": f"{package} is not installed under node_modules (searched upward from {project})"}
    meta = json.loads((pkg_dir / "package.json").read_text())
    res: dict[str, Any] = {"package": package, "version": meta.get("version"), "dir": str(pkg_dir)}
    entry = _types_entry(pkg_dir, meta)
    search_root = pkg_dir
    if entry is None:
        scoped = package[1:].replace("/", "__") if package.startswith("@") else package
        types_pkg = node_package_dir(project, f"@types/{scoped}")
        if types_pkg:
            tmeta = json.loads((types_pkg / "package.json").read_text())
            entry = _types_entry(types_pkg, tmeta)
            search_root = types_pkg
            res["types_from"] = f"@types/{scoped} {tmeta.get('version')}"
    if entry is None:
        res["note"] = "no .d.ts declarations found (untyped package)"
        return res
    res["types_entry"] = str(entry)
    if not symbol:
        text = entry.read_text(errors="replace")
        names = re.findall(r"^\s*export\s+(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?"
                           r"(?:function|class|interface|type|const|let|enum|namespace)\s+(\w+)", text, re.M)
        reexports = re.findall(r"^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['\"]([^'\"]+)['\"]", text, re.M)
        res["exports"] = sorted(set(names))[:300]
        if reexports:
            res["re_exports_from"] = reexports[:50]
        return res
    rx = re.compile(DECL_RE.format(name=re.escape(symbol)), re.M)
    files = sorted(search_root.rglob("*.d.ts"), key=lambda p: (p != entry, len(p.parts)))[:max_files]
    hits = []
    for f in files:
        if "node_modules" in f.relative_to(search_root).parts:
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if symbol not in text:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if rx.match(line) or re.match(rf"^\s*(?:readonly\s+)?{re.escape(symbol)}\s*[(<:?]", line):
                hits.append({"file": f"{f}:{i + 1}", "declaration": _extract_block(lines, i)})
                if len(hits) >= 6:
                    break
        if len(hits) >= 6:
            break
    res["matches"] = hits
    if not hits:
        res["note"] = f"no declaration of {symbol!r} found in {len(files)} .d.ts file(s)"
    return res


def node_versions(project: Path, pattern: str) -> dict:
    nm = None
    for d in (project, *project.parents):
        if (d / "node_modules").is_dir():
            nm = d / "node_modules"
            break
    if not nm:
        return {"error": "no node_modules directory found"}
    out = []
    for p in sorted(nm.iterdir()):
        dirs = sorted(p.iterdir()) if p.name.startswith("@") and p.is_dir() else [p]
        for d in dirs:
            name = f"{p.name}/{d.name}" if p.name.startswith("@") else d.name
            if pattern.lower() not in name.lower():
                continue
            try:
                out.append(f"{name}@{json.loads((d / 'package.json').read_text()).get('version')}")
            except (OSError, ValueError):
                continue
    return {"node_modules": str(nm), "installed": out[:300]}


# ---------------------------------------------------------------- MCP plumbing

TOOLS = [
    {"name": "py_inspect",
     "description": "Inspect a Python object as installed in the project's own interpreter: signature, docstring, "
                    "members (for modules/classes), defining file:line and the installed distribution version. "
                    "target is a dotted path such as 'requests.Session.request' or 'pandas.DataFrame.merge'.",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"}, "project_dir": {"type": "string"},
         "include_project": {"type": "boolean", "description": "also import from the project's ./src and ./"},
         "max_members": {"type": "integer", "default": 80}}, "required": ["target"]}},
    {"name": "py_source",
     "description": "Return the source code of an installed Python function/class/module (truncated to max_chars).",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"}, "project_dir": {"type": "string"}, "include_project": {"type": "boolean"},
         "max_chars": {"type": "integer", "default": 12000}}, "required": ["target"]}},
    {"name": "py_versions",
     "description": "List installed Python distributions (name==version) in the project's interpreter whose name "
                    "contains pattern (empty pattern lists all).",
     "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "project_dir": {"type": "string"}}}},
    {"name": "node_types",
     "description": "Read TypeScript declarations of a package installed in node_modules (falls back to @types/*). "
                    "With symbol: the declaration(s) of that function/class/interface/type with JSDoc and file:line. "
                    "Without: the package version and its exported names.",
     "inputSchema": {"type": "object", "properties": {
         "package": {"type": "string"}, "symbol": {"type": "string"}, "project_dir": {"type": "string"}},
         "required": ["package"]}},
    {"name": "node_versions",
     "description": "List packages installed in the nearest node_modules (name@version) whose name contains pattern.",
     "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "project_dir": {"type": "string"}}}},
]


def call_tool(name: str, args: dict) -> dict:
    project = project_dir(args.get("project_dir"))
    if name == "py_inspect":
        return probe(project, {"op": "inspect", "target": args["target"], "max_members": args.get("max_members", 80)},
                     bool(args.get("include_project")))
    if name == "py_source":
        return probe(project, {"op": "source", "target": args["target"], "max_chars": args.get("max_chars", 12000)},
                     bool(args.get("include_project")))
    if name == "py_versions":
        return probe(project, {"op": "versions", "target": args.get("pattern", "")}, False)
    if name == "node_types":
        return node_lookup(project, args["package"], args.get("symbol"))
    if name == "node_versions":
        return node_versions(project, args.get("pattern", ""))
    raise KeyError(name)


def format_result(name: str, data: dict) -> str:
    if name == "py_source" and "source" in data:
        head = {k: v for k, v in data.items() if k != "source"}
        return json.dumps(head, indent=1) + "\n\n" + data["source"]
    if name == "node_types" and data.get("matches"):
        head = {k: v for k, v in data.items() if k != "matches"}
        blocks = [f"// {m['file']}\n{m['declaration']}" for m in data["matches"]]
        return json.dumps(head, indent=1) + "\n\n" + "\n\n".join(blocks)
    return json.dumps(data, indent=1)


def respond(msg_id: Any, result: Any = None, error: Optional[dict] = None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def handle_message(msg: dict) -> None:
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return  # notification (e.g. notifications/initialized)
    params = msg.get("params") or {}
    if method == "initialize":
        respond(msg_id, {"protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                         "instructions": "Answers API questions from the code installed in this project rather "
                                         "than from memory or web docs: py_inspect / py_source / py_versions for "
                                         "Python, node_types / node_versions for JavaScript and TypeScript."})
    elif method == "ping":
        respond(msg_id, {})
    elif method == "tools/list":
        respond(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        try:
            data = call_tool(name, params.get("arguments") or {})
            respond(msg_id, {"content": [{"type": "text", "text": format_result(name, data)}],
                             "isError": "error" in data})
        except KeyError as e:
            respond(msg_id, error={"code": -32602, "message": f"unknown tool or missing argument: {e}"})
        except Exception as e:  # noqa: BLE001 - report, never crash the server
            respond(msg_id, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    else:
        respond(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            respond(None, error={"code": -32700, "message": "parse error"})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            if isinstance(m, dict):
                handle_message(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
