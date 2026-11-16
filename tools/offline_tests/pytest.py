"""Мини-замена pytest для офлайна. Только то, что нужно этим тестам. Запуск: python tools/offline_tests/run.py tests"""
import sys, os, inspect, importlib.util, tempfile, traceback, time, itertools
from pathlib import Path

class Skip(Exception): pass
def skip(msg=""): raise Skip(msg)
class _Mark:
    def parametrize(self, names, values, **kw):
        def d(f):
            f.__dict__.setdefault("_params", []).append((names, list(values))); return f
        return d
    def skipif(self, cond, reason=""):
        def d(f):
            if cond: f._skip = reason
            return f
        return d
    def __getattr__(self, n): return lambda *a, **k: (lambda f: f)
mark = _Mark()
def fixture(*a, **kw):
    def wrap(f): f._fx = dict(scope=kw.get("scope", "function"), autouse=kw.get("autouse", False)); return f
    return wrap(a[0]) if a and callable(a[0]) else wrap
class raises:
    def __init__(s, exc): s.exc = exc
    def __enter__(s): return s
    def __exit__(s, t, v, tb):
        s.value = v
        if t is None: raise AssertionError('DID NOT RAISE ' + getattr(s.exc, '__name__', str(s.exc)))
        return issubclass(t, s.exc)

sys.modules["pytest"] = sys.modules[__name__]

class Req:
    def __init__(s, run, names): s.run, s.fixturenames = run, names
    def getfixturevalue(s, n): return s.run.get(n)

class Run:
    def __init__(s, fx): s.fx, s.cache, s.fin, s.local, s.tmp = fx, {}, [], {}, []
    def get(s, name, local=None):
        if name == "tmp_path":
            p = Path(tempfile.mkdtemp(prefix="t-")); return p
        if name == "request": return Req(s, list(s.local.get("__names__", [])))
        if name in s.local: return s.local[name]
        f = s.fx[name]; sc = f._fx["scope"]
        if sc == "session" and name in s.cache: return s.cache[name]
        args = [s.get(a) for a in inspect.signature(f).parameters]
        if inspect.isgeneratorfunction(f):
            g = f(*args); v = next(g); (s.fin.append if sc == "function" else s.sess_fin.append)(g)
        else: v = f(*args)
        s.local[name] = v
        if sc == "session": s.cache[name] = v
        return v
    sess_fin = []

def main(paths, only=None):
    root = Path(paths[0]).resolve().parent if Path(paths[0]).is_file() else Path(paths[0]).resolve()
    sys.path.insert(0, str(root)); sys.path.insert(0, str(root.parent))
    def load(p):
        spec = importlib.util.spec_from_file_location(p.stem, p); m = importlib.util.module_from_spec(spec); sys.modules[p.stem] = m; spec.loader.exec_module(m); return m
    conf = load(root / "conftest.py"); fx = {n: v for n, v in vars(conf).items() if hasattr(v, "_fx")}
    files = []
    for a in paths:
        a = Path(a); files += sorted(a.glob("test_*.py")) if a.is_dir() else [a]
    run = Run(fx); res = dict(passed=0, failed=0, skipped=0); fails = []
    cache_server = {}
    for f in files:
        mod = load(f); fx2 = dict(fx); fx2.update({n: v for n, v in vars(mod).items() if hasattr(v, "_fx")}); run.fx = fx2
        for n, fn in list(vars(mod).items()):
            if not n.startswith("test_") or not callable(fn): continue
            if only and only not in n: continue
            combos = [{}]
            for names, vals in getattr(fn, "_params", []):
                ns = [x.strip() for x in names.split(",")]; new = []
                for c in combos:
                    for v in vals:
                        v = v if len(ns) > 1 else (v,); d = dict(c); d.update(dict(zip(ns, v))); new.append(d)
                combos = new
            for c in combos:
                tid = f"{f.name}::{n}" + (str(list(c.values())) if c else "")
                if getattr(fn, "_skip", None) is not None: res["skipped"] += 1; continue
                params = list(inspect.signature(fn).parameters)
                run.local = dict(c); run.fin = []
                run.local["__names__"] = [p for p in params] + [a for a, v in fx2.items() if v._fx["autouse"]] 
                try:
                    for a, v in fx2.items():
                        if v._fx["autouse"]:
                            run.local["__names__"] = list(set(run.local["__names__"]))
                            if "server" in params: run.local["__names__"].append("server")
                            run.get(a)
                    args = [run.get(p) for p in params]
                    fn(*args); res["passed"] += 1
                except Skip: res["skipped"] += 1
                except BaseException:
                    res["failed"] += 1; fails.append((tid, traceback.format_exc()))
                    print("FAIL", tid, flush=True)
                finally:
                    for g in reversed(run.fin):
                        try: next(g)
                        except StopIteration: pass
    for g in reversed(Run.sess_fin):
        try: next(g)
        except StopIteration: pass
    for t, tb in fails: print("=" * 20, t); print(tb[-1800:])
    print(f"{res['passed']} passed, {res['failed']} failed, {res['skipped']} skipped")
    return 1 if res["failed"] else 0
