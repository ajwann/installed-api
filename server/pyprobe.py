"""Runs INSIDE the project's Python interpreter (any 3.x). Prints one JSON object.

argv[1] is a JSON request: {"op": "inspect"|"source"|"versions", "target": "...", ...}
Kept dependency-free and compatible with old interpreters on purpose.
"""
import importlib
import inspect
import json
import sys


def resolve(target):
    parts = target.split(".")
    mod, err = None, None
    for i in range(len(parts), 0, -1):
        name = ".".join(parts[:i])
        try:
            mod = importlib.import_module(name)
            rest = parts[i:]
            break
        except ImportError as e:  # keep the deepest import error for the report
            err = err or "%s: %s" % (type(e).__name__, e)
            continue
    if mod is None:
        raise LookupError("cannot import any prefix of %r (%s)" % (target, err))
    obj = mod
    for attr in rest:
        if not hasattr(obj, attr):
            import difflib
            names = dir(obj)
            near = difflib.get_close_matches(attr, names, n=6, cutoff=0.6)
            near += [n for n in names if attr.lower() in n.lower() and n not in near][:4]
            raise LookupError("%r has no attribute %r%s" % (getattr(obj, "__name__", obj), attr,
                                                            "; similar: " + ", ".join(near) if near else ""))
        obj = getattr(obj, attr)
    return mod, obj


def is_stdlib(top):
    if top in sys.builtin_module_names:
        return True
    names = getattr(sys, "stdlib_module_names", None)  # 3.10+
    if names is not None:
        return top in names
    import os
    import sysconfig
    f = getattr(sys.modules.get(top), "__file__", None)
    if not f:
        return False
    f = os.path.realpath(f)
    stdlib = os.path.realpath(sysconfig.get_paths()["stdlib"])
    return f.startswith(stdlib + os.sep) and "site-packages" not in f and "dist-packages" not in f


def dists_for(metadata, top):
    """Distribution names providing top-level import name `top`."""
    pd = getattr(metadata, "packages_distributions", None)  # 3.10+
    if pd is not None:
        return pd().get(top) or []
    out = []
    for d in metadata.distributions():
        tops = (d.read_text("top_level.txt") or "").split()
        if not tops:
            tops = [p.parts[0].split(".")[0] for p in (d.files or []) if p.parts]
        if top in tops and d.metadata["Name"]:
            out.append(d.metadata["Name"])
    return out


def dist_version(module):
    top = (getattr(module, "__name__", "") or "").split(".")[0]
    if is_stdlib(top):
        return "stdlib (Python %s)" % sys.version.split()[0]
    try:
        from importlib import metadata
    except ImportError:
        return getattr(module, "__version__", None)
    try:
        dists = dists_for(metadata, top) or [top]
        return "%s %s" % (dists[0], metadata.version(dists[0]))
    except Exception:
        return getattr(sys.modules.get(top), "__version__", None)


def sig(obj):
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return getattr(obj, "__text_signature__", None)


def kind(obj):
    for k in ("module", "class", "function", "method", "builtin", "routine"):
        if getattr(inspect, "is" + k)(obj):
            return k
    return type(obj).__name__


def where(obj):
    try:
        f = inspect.getsourcefile(obj) or inspect.getfile(obj)
    except TypeError:
        return None
    try:
        line = inspect.getsourcelines(obj)[1]
    except (OSError, TypeError):
        line = None
    return "%s:%s" % (f, line) if line else f


def members(obj, limit):
    out = []
    for name in sorted(dir(obj)):
        if name.startswith("_") and name not in ("__init__", "__call__"):
            continue
        try:
            m = getattr(obj, name)
        except Exception:
            continue
        if inspect.ismodule(m) and inspect.ismodule(obj) and not getattr(m, "__name__", "").startswith(obj.__name__):
            continue
        entry = {"name": name, "kind": kind(m)}
        if callable(m):
            s = sig(m)
            if s:
                entry["signature"] = s
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def main():
    req = json.loads(sys.argv[1])
    for extra in req.get("sys_path") or []:
        sys.path.insert(0, extra)
    op = req["op"]
    res = {"python": sys.version.split()[0], "executable": sys.executable}
    if op == "versions":
        from importlib import metadata
        pat = (req.get("target") or "").lower()
        res["installed"] = sorted({"%s==%s" % (d.metadata["Name"], d.version) for d in metadata.distributions()
                                   if d.metadata["Name"] and pat in d.metadata["Name"].lower()})[:300]
        print(json.dumps(res))
        return
    mod, obj = resolve(req["target"])
    res.update({"target": req["target"], "kind": kind(obj), "version": dist_version(mod), "defined_at": where(obj)})
    if op == "inspect":
        s = sig(obj) if callable(obj) else None
        if s:
            res["signature"] = s
        doc = inspect.getdoc(obj) or ""
        res["doc"] = doc[: int(req.get("max_doc", 1500))]
        if inspect.isclass(obj) or inspect.ismodule(obj):
            res["members"] = members(obj, int(req.get("max_members", 80)))
        if inspect.isclass(obj):
            res["mro"] = [c.__module__ + "." + c.__qualname__ for c in obj.__mro__[1:6]]
    elif op == "source":
        try:
            src = inspect.getsource(obj)
        except (OSError, TypeError) as e:
            src = "<no Python source: %s>" % e
        res["source"] = src[: int(req.get("max_chars", 12000))]
        res["truncated"] = len(src) > int(req.get("max_chars", 12000))
    print(json.dumps(res, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}))
