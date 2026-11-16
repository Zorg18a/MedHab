#!/usr/bin/env python3
"""GameSweep — находит старые версии игр в библиотеке и отправляет их в Корзину.
Реализовано по SPEC.md. Только стандартная библиотека. Живёт внутри MediaHub (раздел «Игры» → «Версии и чистка»):
своего сервера и окна больше нет, приложение вызывает Store и функции разбора напрямую.

  python gamesweep.py --selftest      проверка логики без браузера и сервера
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

APP, VERSION = "GameSweep", "1.1"
IS_WIN = os.name == "nt"

# ===========================================================================
#  1. Что считается игрой (SPEC §2)
# ===========================================================================
ARCH = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz")
CATEGORY = re.compile(r"^(new|n|part|batch|vol)[ _-]?\d+$", re.I)
SKIP = {"$recycle.bin", "system volume information"}


def _skipped(name: str) -> bool:
    low = name.lower()
    return name.startswith(".") or low.startswith("_gamesweep") or low in SKIP


def _tree_stats(top: str) -> tuple[int, float]:
    """(сумма размеров, самый свежий mtime) папки, без обхода ссылок на папки."""
    total, newest, stack = 0, 0.0, [top]
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir():
                        if not e.is_symlink():
                            stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                    total += st.st_size
                    newest = max(newest, st.st_mtime)
                except OSError:
                    continue
    return total, newest


def list_games(root: str, layout: str = "auto") -> list[dict]:
    """Папки и архивы библиотеки (без размеров — их считает scan_library параллельно)."""
    out: list[dict] = []

    def add(e, is_dir):
        out.append({"name": e.name, "path": e.path, "type": "folder" if is_dir else "archive"})

    def visit(path, can_expand):
        try:
            it = os.scandir(path)
        except OSError:
            return
        with it:
            for e in sorted(it, key=lambda x: x.name.lower()):
                if _skipped(e.name):
                    continue
                try:
                    is_dir = e.is_dir()
                except OSError:
                    continue
                if is_dir:
                    category = layout == "nested" or (layout == "auto" and CATEGORY.match(e.name))
                    if can_expand and category:
                        visit(e.path, False)
                    else:
                        add(e, True)
                elif e.name.lower().endswith(ARCH):
                    add(e, False)

    visit(root, True)
    return out


def scan_library(root: str, layout: str = "auto", progress=None, workers: int = 4) -> list[dict]:
    games = list_games(root, layout)

    def fill(g):
        try:
            if g["type"] == "folder":
                g["size"], g["mtime"] = _tree_stats(g["path"])
            else:
                st = os.stat(g["path"])
                g["size"], g["mtime"] = st.st_size, st.st_mtime
        except OSError:
            g["size"], g["mtime"] = 0, 0.0
        if progress:
            progress()
        return g

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fill, games))


# ===========================================================================
#  2. Название и версия из имени (SPEC §3)
# ===========================================================================
JUNK = set("win windows pc x64 x86 linux mac macos android apk public release final full rus eng multi "
           "setup portable".split())
PLATFORM = re.compile(r"(?i)^(?:win(?:dows)?|linux|mac(?:os)?|pc|x)(?:32|64|86)$|^(?:32|64)bit$")  # Windows64, win32, x64, 64bit (но не голое «64» в названии)
NA, NB = r"(?<![^\W_])", r"(?![^\W_])"                    # «не буква/цифра рядом» (подчёркивание — разделитель)
COPY = re.compile(r"(?i)\(\s*\d+\s*\)|\(\s*(?:copy|копия)\s*\d*\s*\)|" + NA + r"(?:copy|копия)\s*\d*" + NB)
DOTTED = re.compile(r"(?i)" + NA + r"(?:ver(?:sion)?\.?\s*|v\s*)?(\d+(?:\.\d+)+)([a-z]?)" + NB)
V_ONLY = re.compile(r"(?i)" + NA + r"v\s*(\d+)([a-z]?)" + NB)
DATESTAMP = re.compile(r"(?i)" + NA + r"(20\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))([a-z]?)" + NB)   # сборка датой: 20260828c
CHAPTER = re.compile(r"(?i)" + NA + r"(?:ch(?:apter)?|ep(?:isode)?)\.?\s*(\d+)" + NB)


def parse_name(name: str) -> dict:
    """{'base','key','nums','suffix','text','kind'}; nums=None, если версии в имени нет."""
    label = name
    for ext in ARCH:
        if label.lower().endswith(ext):
            label = label[:-len(ext)]
            break
    nums, suffix, text, kind, m = None, "", "", None, None
    ms = list(DOTTED.finditer(label)) or list(V_ONLY.finditer(label)) or list(DATESTAMP.finditer(label))
    if ms:
        m = ms[-1]                                          # последнее: «Game 2 v1.0» — двойка часть названия
        nums, suffix, kind = tuple(int(x) for x in m.group(1).split(".")), m.group(2).lower(), "v"
        text = m.group(1) + suffix
    else:
        ms = list(CHAPTER.finditer(label))
        if ms:
            m = ms[-1]
            nums, kind, text = (int(m.group(1)),), "ch", "Ch." + m.group(1)
    rest = label if m is None else label[:m.start()] + " " + label[m.end():]
    tokens = [t for t in re.split(r"[\W_]+", COPY.sub(" ", rest)) if t and t.lower() not in JUNK and not PLATFORM.match(t)]
    return {"base": " ".join(tokens), "key": "".join(tokens).casefold(),
            "nums": nums, "suffix": suffix, "text": text, "kind": kind}


# ===========================================================================
#  3. Группы и решения (SPEC §4)
# ===========================================================================
def _vkey(m: dict, width: int):
    return tuple(m["nums"]) + (0,) * (width - len(m["nums"])), m["suffix"]


def _ambiguous(a: str, b: str) -> bool:
    """0.9 и 0.10: как числа 10 > 9, как дроби 0.10 < 0.9. Целые (v2/v10) не спорные."""
    pa, pb = re.sub(r"[a-z]$", "", a).split("."), re.sub(r"[a-z]$", "", b).split(".")
    for i, (x, y) in enumerate(zip(pa, pb)):
        if x != y:
            if i == 0:
                return False
            n = max(len(x), len(y))
            return (int(x) > int(y)) != (x.ljust(n, "0") > y.ljust(n, "0"))
    return False


def _row(m: dict, status: str, reason: str) -> dict:
    ver = ("v" + m["text"]) if m["kind"] == "v" else (m["text"] or "—")
    return {"path": m["path"], "name": m["name"], "type": m["type"], "size": m["size"], "mtime": m["mtime"],
            "version": ver, "status": status, "reason": reason}


def build_groups(games: list[dict]) -> list[dict]:
    buckets: dict[str, list] = {}
    for g in games:
        m = {**g, **parse_name(g["name"])}
        if m["key"]:
            buckets.setdefault(m["key"], []).append(m)
    groups = []
    for key, ms in buckets.items():
        if len(ms) < 2:
            continue
        grp = _group_by_version(ms) or _group_by_date(ms)
        if grp:
            grp["key"] = key
            grp["free"] = sum(r["size"] for r in grp["members"] if r["status"] in ("старая", "дубль"))
            groups.append(grp)
    groups.sort(key=lambda g: g["title"].casefold())
    return groups


def _group_by_version(ms):
    dominant = "v" if any(m["kind"] == "v" for m in ms) else "ch"
    comp = [m for m in ms if m["kind"] == dominant]
    if len({(m["nums"], m["suffix"]) for m in comp}) < 2:
        return None
    w = max(len(m["nums"]) for m in comp)
    comp.sort(key=lambda m: _vkey(m, w), reverse=True)
    top_key = _vkey(comp[0], w)
    tops = [m for m in comp if _vkey(m, w) == top_key]
    keeper = sorted(tops, key=lambda m: (m["type"] != "folder", -m["mtime"]))[0]      # папка лучше архива
    notes, sure, rows = [], True, []
    if len(tops) > 1:
        sure = False
        notes.append("новейшая версия лежит в нескольких экземплярах")
    for m in comp:
        if m is keeper:
            rows.append(_row(m, "оставить", "новейшая версия"))
        elif _vkey(m, w) == top_key:
            rows.append(_row(m, "дубль", "та же версия, что у оставляемой"))
        else:
            rows.append(_row(m, "старая", f"{m['text']} < {keeper['text']}"))
            if _ambiguous(m["text"], keeper["text"]):
                sure = False
                notes.append(f"{m['text']} и {keeper['text']}: порядок зависит от того, дробь это или число")
    for m in ms:
        if m not in comp:
            sure = False
            rows.append(_row(m, "вручную", "версия в имени не найдена или другого вида"))
    return {"title": keeper["base"], "sure": sure, "mode": "версия", "notes": notes, "members": rows}


def _group_by_date(ms):
    dated = sorted((m for m in ms if m["mtime"]), key=lambda m: -m["mtime"])
    if len(dated) < 2:
        return None
    top = dated[0]
    rows = [_row(top, "оставить", "самые свежие файлы (версию определить не удалось)")]
    for m in dated[1:]:
        days = (top["mtime"] - m["mtime"]) / 86400
        rows.append(_row(m, "старая", f"файлы старее на {int(days)} дн.") if days >= 1
                    else _row(m, "вручную", "даты почти совпадают"))
    return {"title": top["base"], "sure": False, "mode": "дата", "members": rows,
            "notes": ["версия в именах не найдена — решение по дате изменения, проверьте вручную"]}


def summary(games: list[dict], groups: list[dict]) -> dict:
    old = [r for g in groups for r in g["members"] if r["status"] in ("старая", "дубль")]
    return {"games": len(games), "groups": len(groups), "old": len(old), "free": sum(r["size"] for r in old)}


# ===========================================================================
#  4. Сохранения и Корзина (SPEC §5)
# ===========================================================================
SAVE_DIRS = {"save", "saves", "savedata", "savegame", "savegames"}
SAVE_FILE = re.compile(r"(?i)\.(rpgsave|sav|save)$|^save[\w\- ]*\.(dat|rvdata2?|rxdata|json)$")


def game_root(path: str) -> str:
    """Если папка — обёртка с единственной подпапкой, спускаемся в неё (до 3 раз)."""
    cur = path
    for _ in range(3):
        try:
            with os.scandir(cur) as it:
                ents = list(it)
        except OSError:
            break
        if len(ents) == 1 and ents[0].is_dir() and not ents[0].is_symlink():
            cur = ents[0].path
        else:
            break
    return cur


def find_saves(path: str, limit: int = 5) -> list[str]:
    top, found, stack = game_root(path), [], []
    stack.append(top)
    while stack and len(found) < limit:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir():
                        if e.name.lower() in SAVE_DIRS and any(True for _ in os.scandir(e.path)):
                            found.append(os.path.relpath(e.path, top) + os.sep)
                        if not e.is_symlink():
                            stack.append(e.path)
                    elif SAVE_FILE.search(e.name):
                        found.append(os.path.relpath(e.path, top))
                except OSError:
                    continue
    return found


def copy_saves(src: dict, dst: dict) -> tuple[int, list[str]]:
    """Сохранения старой версии → новая (папка→папка, на то же место, существующее не перезаписываем)."""
    if src["type"] != "folder" or dst["type"] != "folder":
        return 0, ["одна из версий — архив: распакуйте её"]
    s_root, d_root = game_root(src["path"]), game_root(dst["path"])
    rels = find_saves(src["path"], limit=100000)
    dirs = [r for r in rels if r.endswith(os.sep)]
    rels = [r for r in rels if r.endswith(os.sep) or not any(r.startswith(d) for d in dirs)]
    copied, errors = 0, []
    for r in rels:
        pairs = []
        if r.endswith(os.sep):
            for cur, _d, files in os.walk(os.path.join(s_root, r)):
                pairs += [(os.path.join(cur, f), os.path.join(d_root, os.path.relpath(os.path.join(cur, f), s_root)))
                          for f in files]
        else:
            pairs.append((os.path.join(s_root, r), os.path.join(d_root, r)))
        for sf, df in pairs:
            if os.path.exists(df):
                continue
            try:
                os.makedirs(os.path.dirname(df), exist_ok=True)
                shutil.copy2(sf, df)
                copied += 1
            except OSError as e:
                errors.append(f"{os.path.basename(sf)}: {e}")
    return copied, errors


def to_trash(path: str, root: str) -> tuple[bool, str]:
    """Windows — системная Корзина (восстановимо). Иначе — _GameSweep_Trash в корне библиотеки."""
    path = os.path.abspath(path)
    if IS_WIN:
        import ctypes
        from ctypes import wintypes

        class OP(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("aborted", wintypes.BOOL),
                        ("maps", ctypes.c_void_p), ("title", wintypes.LPCWSTR)]
        op = OP(None, 3, path + "\0", None, 0x40 | 0x10 | 0x400 | 0x4, False, None, None)   # FO_DELETE + ALLOWUNDO
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return (rc == 0 and not op.aborted), ("" if rc == 0 else f"код {rc}")
    try:
        dest = Path(root) / "_GameSweep_Trash" / time.strftime("%Y%m%d_%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(path, str(dest / os.path.basename(path)))
        return True, ""
    except OSError as e:
        return False, str(e)


# ===========================================================================
#  4б. Вкладки браузера против игр (SPEC §8)
# ===========================================================================
GAME_HOSTS = ("f95zone.to", "allthefallen.moe", "pornolab.net")
TAB_MARKS = {"final", "completed", "complete", "demo", "prologue", "teaser"}
_VTOK = re.compile(r"^(?:v\d+[a-z]?|(?:ch|ep)\d+)$")
_NTOK = re.compile(r"^(\d+)([a-z]?)$")
_PRE = re.compile(r"^(?:dev|alpha|beta|rc|hotfix|fix|test)\d*$")
_TITLE_BR = re.compile(r"^(?P<name>.+?)\s*\[(?P<ver>[^\]]+)\]\s*\[(?P<dev>[^\]]+)\]")
_MD = re.compile(r"^\[(.*)\]\((\S+)\)$")
_TU = re.compile(r"^(?:(.*?)\s*[\t|–—-]\s*)?(https?://\S+)$")


def _ver(nums, suffix="", kind="v", pre=False) -> dict:
    text = (".".join(str(n) for n in nums) + suffix) if kind == "v" else f"Ch.{nums[0]}"
    return {"nums": tuple(nums), "suffix": suffix, "kind": kind, "text": text, "pre": pre}


def version_of(text: str):
    p = parse_name(text)
    return None if p["nums"] is None else _ver(p["nums"], p["suffix"], p["kind"])


def slug_info(slug: str):
    """'noir-v0-1-3-bawtsforbrains' -> (['noir'], версия 0.1.3, []). Студия после версии отбрасывается."""
    toks = [t for t in slug.lower().split("-") if t]
    idx = next((i for i in range(1, len(toks)) if _VTOK.match(toks[i])), None)
    if idx is None:                                            # без «v»: два числа подряд (1-0-0)
        idx = next((i for i in range(1, len(toks) - 1) if _NTOK.match(toks[i]) and _NTOK.match(toks[i + 1])), None)
    flags = sorted(t for t in set(toks) if t in TAB_MARKS)
    if idx is None:
        return [t for t in toks if t not in TAB_MARKS], None, flags
    c, j = re.match(r"^(ch|ep)(\d+)$", toks[idx]), idx
    if c:
        ver = _ver([int(c.group(2))], kind="ch")
    else:
        m = _NTOK.match(toks[idx].lstrip("v"))
        nums, suf = [int(m.group(1))], m.group(2)
        while not suf and j + 1 < len(toks) and _NTOK.match(toks[j + 1]):
            m = _NTOK.match(toks[j + 1])
            nums.append(int(m.group(1)))
            suf = m.group(2)
            j += 1
        ver = _ver(nums, suf)
    ver["pre"] = j + 1 < len(toks) and bool(_PRE.match(toks[j + 1]))
    return toks[:idx], ver, flags


def pornolab_info(title: str):
    """Название(я) и версия из заголовка темы; блок меток не разбирается и не сохраняется."""
    t = re.sub(r"\s*::\s*PornoLab.*$", "", title).strip()
    head = re.split(r"\s*[\[(]", t, 1)[0]
    names = [a.strip() for a in head.split("/") if re.search(r"[A-Za-z]{3}", a)]
    ver = None
    for b in re.findall(r"\[([^\]]*)\]", t):
        b = b.strip()
        if re.match(r"^\d{4}\b", b):
            continue
        if re.match(r"(?i)^(v|ver\.?\s*)?\d", b):
            ver = version_of(b)
            break
    return names, ver


def analyze_tab(title: str, url: str, line: str) -> dict:
    tab = {"line": line, "url": url, "title": title, "host": "", "kind": "other", "names": [], "ver": None,
           "flags": [], "source": "", "id": ""}
    if not url.startswith("http"):
        tab["kind"] = "service"
        return tab
    p = urlparse(url)
    host = tab["host"] = p.netloc.lower().removeprefix("www.")
    if host not in GAME_HOSTS:
        return tab
    loaded = bool(title) and title != url
    if host == "pornolab.net":
        m = re.search(r"[?&]t=(\d+)", url)
        if "viewtopic" not in p.path or not m:
            tab["kind"] = "service"
            return tab
        tab.update(id=m.group(1), kind="game", source="заголовок")
        if loaded:
            tab["names"], tab["ver"] = pornolab_info(title)
        return tab
    m = re.search(r"(?:/threads/|resources/|threads/)([^/?#]+?)\.(\d+)(?:[/?#]|$)", url)
    if not m:
        tab["kind"] = "service"
        return tab
    slug, tab["id"], tab["kind"] = m.group(1), m.group(2), "game"
    tm = _TITLE_BR.match(title) if loaded else None
    if tm:
        word = tm.group("ver").strip().lower()
        tab.update(names=[tm.group("name").strip()], ver=version_of(tm.group("ver")),
                   flags=[word] if word in TAB_MARKS else [], source="заголовок")
    else:
        toks, ver, flags = slug_info(slug)
        tab.update(names=[" ".join(toks)], ver=ver, flags=flags, source="адрес")
    return tab


def parse_tabs(text: str):
    """(вкладки без дублей, сколько дублей убрано). Форматы: [заголовок](адрес), «заголовок – адрес», адрес."""
    tabs, seen, dups = [], set(), 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = _MD.match(s) or _TU.match(s)
        title, url = ((m.group(1) or "").strip(), m.group(2)) if m else (s, "")
        tab = analyze_tab(title or url, url, s)
        key = (tab["host"], tab["id"]) if tab["id"] else (url.split("#")[0] or s)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        tabs.append(tab)
    return tabs, dups


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\W_]+", s.casefold()) if t and t not in JUNK]


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def index_locals(games: list[dict]) -> dict:
    """ключ названия -> {tokens, entries, best}; best — новейшая версия игры на ПК."""
    by_key: dict[str, dict] = {}
    for g in games:
        p = parse_name(g["name"])
        if p["key"]:
            by_key.setdefault(p["key"], {"key": p["key"], "tokens": _tokens(p["base"]), "entries": []})["entries"].append((p, g))

    def rank(e):
        p, g = e
        nums = tuple(p["nums"] or ())
        return (p["nums"] is not None, nums + (0,) * (8 - len(nums)), p["suffix"], g["mtime"])
    for loc in by_key.values():
        loc["best"] = max(loc["entries"], key=rank)
    return by_key


def match_tab(tab: dict, by_key: dict):
    """(оценка, игра, почему, слов) для лучшего совпадения или None (SPEC §8.4)."""
    best, has_v = None, tab["ver"] is not None
    for name in tab["names"]:
        T = _tokens(name)
        if not T:
            continue
        key, tset = "".join(T), set(T)
        dT = {t for t in T if t.isdigit()}
        cands = []
        if key in by_key and len(key) >= 3:
            cands.append((1.0, by_key[key], "точное совпадение", len(T)))
        else:
            for loc in by_key.values():
                L = loc["tokens"]
                Ls, dL = set(L), {t for t in L if t.isdigit()}
                if len(L) >= 2 and Ls == tset:
                    cands.append((0.9, loc, "те же слова", len(L)))
                elif len(L) >= 2 and Ls < tset:
                    if dT <= dL:                                       # лишнее число = другая часть игры
                        cands.append((0.55 if has_v else 0.8, loc, "слова игры внутри названия вкладки", len(L)))
                elif len(T) >= 2 and tset < Ls and dL <= dT:
                    cands.append((0.75, loc, "слова вкладки внутри названия игры", len(T)))
                elif len(key) >= 8 and len(loc["key"]) >= 8 and abs(len(key) - len(loc["key"])) <= 1 \
                        and _lev(key, loc["key"]) <= 1:
                    cands.append((0.7, loc, "опечатка в названии", len(T)))
        for c in cands:
            if best is None or c[0] > best[0]:
                best = c + (key,)
    return best


def tab_verdict(tab: dict, loc: dict):
    """(вердикт, уверенно) для найденной игры (SPEC §8.5)."""
    pv, (lp, _g) = tab["ver"], loc["best"]
    if not pv or lp["nums"] is None or lp["kind"] != pv["kind"]:
        return "unknown_ver", True
    w = max(len(pv["nums"]), len(lp["nums"]))
    a = _vkey({"nums": pv["nums"], "suffix": pv["suffix"]}, w)
    b = _vkey({"nums": lp["nums"], "suffix": lp["suffix"]}, w)
    if a == b:
        return "same", True
    return ("update" if b < a else "newer_pc"), not _ambiguous(pv["text"], lp["text"])


def analyze_tabs(text: str, games: list[dict]) -> dict:
    tabs, dups = parse_tabs(text)
    by_key = index_locals(games)
    out, counts = [], {}
    for t in tabs:
        r = {"line": t["line"], "url": t["url"], "title": t["title"], "host": t["host"], "kind": t["kind"],
             "name": "", "version": "", "flags": t["flags"], "source": t["source"], "verdict": "", "sure": True,
             "why": "", "local": None}
        if t["names"]:
            r["name"] = t["names"][0] if t["source"] == "заголовок" else " ".join(w.capitalize() for w in t["names"][0].split())
        if t["ver"]:
            r["version"] = ("v" + t["ver"]["text"]) if t["ver"]["kind"] == "v" else t["ver"]["text"]
        if t["kind"] == "game":
            m = match_tab(t, by_key) if t["names"] else None
            if not t["names"]:
                r.update(verdict="unparsed", why="название не удалось разобрать (нет латинского названия или заголовок не загружен)")
            elif not m:
                r.update(verdict="missing", why="похожей игры на ПК нет")
            else:
                score, loc, why, ntok, key = m
                verdict, vsure = tab_verdict(t, loc)
                lp, lg = loc["best"]
                sure_match = (score == 1.0 and len(key) >= 5) or (score in (0.9, 0.8, 0.75) and ntok >= 3)
                r.update(verdict=verdict, why=why, sure=vsure and sure_match,
                         local={"name": lg["name"], "path": lg["path"], "type": lg["type"], "count": len(loc["entries"]),
                                "version": (("v" + lp["text"]) if lp["kind"] == "v" else lp["text"]) if lp["nums"] else ""})
        if r["verdict"]:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        out.append(r)
    games_n = sum(1 for r in out if r["kind"] == "game")
    return {"tabs": out, "summary": {
        "total": len(out), "dups": dups, "games": games_n, "other": sum(1 for r in out if r["kind"] == "other"),
        "service": sum(1 for r in out if r["kind"] == "service"), "counts": counts,
        "have": counts.get("same", 0) + counts.get("newer_pc", 0) + counts.get("unknown_ver", 0), "update": counts.get("update", 0)}}


def reveal(path: str) -> bool:
    """Показать место файла: Windows — выделить в Проводнике, macOS — в Finder, Linux — открыть папку."""
    path = os.path.abspath(path)
    try:
        if IS_WIN:
            subprocess.Popen('explorer /select,"%s"' % path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        return True
    except OSError:
        return False


# ===========================================================================
#  5. Состояние и сервер (SPEC §5.2, §5.4)
# ===========================================================================
class Store:
    def __init__(self, root=""):
        self.lock = threading.Lock()
        self.root, self.layout = root, "auto"
        self.running, self.done, self.total, self.error = False, 0, 0, ""
        self.games: list[dict] = []
        self.groups: list[dict] = []
        self.scanned = False
        self.on_done = None

    def _notify(self):
        cb = self.on_done
        if cb:
            with self.lock:
                games, root = list(self.games), self.root
            try:
                cb(games, root)
            except Exception:
                pass

    def rebuild(self):
        self.groups = build_groups(self.games)

    def snapshot(self) -> dict:
        with self.lock:
            d = {"root": self.root, "layout": self.layout, "running": self.running, "done": self.done,
                 "total": self.total, "error": self.error, "scanned": self.scanned}
            if self.scanned and not self.running:
                d.update(groups=self.groups, summary=summary(self.games, self.groups))
            return d

    def start_scan(self, root: str, layout: str):
        with self.lock:
            if self.running:
                return False
            self.root, self.layout, self.running, self.error = root, layout, True, ""
            self.done = self.total = 0
        threading.Thread(target=self._scan, args=(root, layout), daemon=True).start()
        return True

    def _scan(self, root, layout):
        try:
            with self.lock:
                self.total = len(list_games(root, layout))

            def tick():
                with self.lock:
                    self.done += 1
            games = scan_library(root, layout, tick)
            with self.lock:
                self.games = games
                self.rebuild()
                self.scanned = True
            self._notify()
        except Exception as e:                                   # покажем пользователю, а не молча упадём
            with self.lock:
                self.error = str(e)
        finally:
            with self.lock:
                self.running = False

    def lookup(self, paths):
        index = {m["path"]: (g, m) for g in self.groups for m in g["members"]}
        return [index.get(p) for p in paths]

    def saves(self, paths) -> dict:
        """Сохранения у выбранных версий-папок: {путь: [файлы]}; незнакомые пути и архивы пропускаются."""
        with self.lock:
            found = {p: find_saves(p) for p, ent in zip(paths, self.lookup(paths)) if ent and ent[1]["type"] == "folder"}
        return {p: v for p, v in found.items() if v}

    def reveal(self, path: str) -> bool:
        """Показать в проводнике только то, что есть в списке сканирования (произвольные пути не открываем)."""
        with self.lock:
            known = path in {x["path"] for x in self.games}
        return bool(known and os.path.exists(path) and reveal(path))

    def analyze(self, text: str):
        """Сравнить список вкладок с играми на ПК; None, пока папка не просканирована."""
        with self.lock:
            ready, games = self.scanned and not self.running, list(self.games)
        return analyze_tabs(str(text)[:5_000_000], games) if ready else None

    def trash(self, paths: list[str], saves_mode: str, force: bool = False) -> list[dict]:
        """Сервер сам решает, что можно удалить: клиенту не доверяем (SPEC §5.2).
        Старые версии и дубли удаляются как раньше. Актуальную версию («оставить», «вручную») можно удалить
        только с явным подтверждением force=True (человек видел предупреждение). Корзина восстановима."""
        results, removed, chosen = [], set(), set(paths)
        with self.lock:
            for p, ent in zip(paths, self.lookup(paths)):
                def fail(msg):
                    results.append({"path": p, "ok": False, "msg": msg})
                if not ent:
                    fail("нет в списке — не трогаю")
                    continue
                grp, m = ent
                if m["status"] not in ("старая", "дубль") and not force:
                    fail("не старая версия — нужно отдельное подтверждение")
                    continue
                keeper = next((x for x in grp["members"] if x["status"] == "оставить"), None)
                if not force and (not keeper or keeper["path"] == p or not os.path.exists(keeper["path"])):
                    fail("новейшая версия не найдена на диске")
                    continue
                if not os.path.exists(p):
                    fail("уже нет на диске")
                    continue
                alive = [x for x in grp["members"] if x["path"] not in chosen and os.path.exists(x["path"])]
                target = keeper if keeper in alive else (alive[0] if alive else None)   # куда переносить сохранения
                saves = find_saves(p) if m["type"] == "folder" else []
                if saves and saves_mode == "skip":
                    fail("пропущено: есть сохранения")
                    continue
                if saves and saves_mode == "copy":
                    if not target:
                        fail("некуда скопировать сохранения: не останется ни одной версии")
                        continue
                    _n, errs = copy_saves(m, target)
                    if errs:
                        fail("сохранения не скопированы: " + errs[0])
                        continue
                ok, msg = to_trash(p, self.root)
                results.append({"path": p, "ok": ok, "msg": msg})
                if ok:
                    removed.add(p)
            if removed:
                self.games = [g for g in self.games if g["path"] not in removed]
                self.rebuild()
        if removed:
            self._notify()
        return results


# ===========================================================================
#  7. Самопроверка (примеры из SPEC §7)
# ===========================================================================
def selftest() -> int:
    import subprocess
    import tempfile

    ok_n = fail_n = 0

    def check(name, cond, extra=""):
        nonlocal ok_n, fail_n
        ok_n, fail_n = ok_n + bool(cond), fail_n + (not cond)
        print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"   {extra}"))

    print("== Имена и версии (SPEC §3, §7) ==")
    table = [("Slave_Of_Passion_1.0.3_-_Win.zip", "slaveofpassion", "1.0.3"),
             ("Together_Again_1.0.3_-_Win.zip", "togetheragain", "1.0.3"),
             ("Dwarfing_Dreams_v0.2.3.1a.zip", "dwarfingdreams", "0.2.3.1a"),
             ("REC_v0.5.6.0.zip", "rec", "0.5.6.0"), ("nemurimouto_v0.10_win.zip", "nemurimouto", "0.10"),
             ("YesIamAFurry-0.2.7-pc.zip", "yesiamafurry", "0.2.7"), ("Hypno_card.zip", "hypnocard", ""),
             ("TogetherAgain v1.1.zip", "togetheragain", "1.1"), ("wife_schooooool (2).rar", "wifeschooooool", ""),
             ("Mystery Tale copy2", "mysterytale", "")]
    for name, key, ver in table:
        p = parse_name(name)
        check(f"{name} → {key} / {ver or '—'}", p["key"] == key and p["text"] == ver, str(p))
    check("«Game 2 v1.0»: двойка — часть названия", parse_name("Game 2 v1.0")["key"] == "game2")

    print("\n== Группы (SPEC §4) ==")
    mk = lambda name, mt=1.7e9, tp="archive": {"name": name, "path": "/x/" + name, "type": tp, "size": 100, "mtime": mt}
    g = build_groups([mk("ADeckOfHex-v1.15.zip"), mk("ADeckOfHex-v1.21.zip"), mk("Hypno_card.zip")])
    check("ADeckOfHex: 1.21 оставить, 1.15 старая, уверенная; Hypno_card (одна) не показана",
          len(g) == 1 and [(r["version"], r["status"]) for r in g[0]["members"]] == [("v1.21", "оставить"), ("v1.15", "старая")]
          and g[0]["sure"])
    g = build_groups([mk("Lust_Academy_v1.0"), mk("Lust_Academy_2_v1.0"), mk("Lust_Academy_2_v1.3")])
    check("Lust Academy и Lust Academy 2 — разные игры", len(g) == 1 and g[0]["title"] == "Lust Academy 2")
    g = build_groups([mk("Zephyr_v0.9"), mk("Zephyr_v0.10")])
    check("Zephyr 0.9/0.10: новее 0.10, группа неуверенная", g[0]["members"][0]["version"] == "v0.10" and not g[0]["sure"])
    g = build_groups([mk("Zephyr_v2"), mk("Zephyr_v10")])
    check("Zephyr v2/v10: новее 10, уверенно", g[0]["members"][0]["version"] == "v10" and g[0]["sure"])
    g = build_groups([mk("Game Ch.2"), mk("Game Ch.10")])
    check("главы: Ch.10 новее Ch.2", g[0]["members"][0]["version"] == "Ch.10")
    g = build_groups([mk("Foo_v1.0"), mk("Foo_v1.0 (2)"), mk("Foo_v0.5"), mk("Foo")])
    st = sorted(r["status"] for r in g[0]["members"])
    check("одна версия дважды → дубль; без версии → вручную", st == sorted(["дубль", "оставить", "старая", "вручную"]), str(st))
    g = build_groups([mk("Hypno_card.zip", 1.7e9), mk("Hypno_card (2).zip", 1.7e9 + 5 * 86400)])
    check("версий нет → по дате, неуверенно: новее (2)",
          g[0]["mode"] == "дата" and not g[0]["sure"] and g[0]["members"][0]["name"] == "Hypno_card (2).zip")
    g = build_groups([mk("Bar.zip", 1.7e9), mk("Bar (2).zip", 1.7e9 + 60)])
    check("даты почти совпадают → вручную", g[0]["members"][1]["status"] == "вручную")

    print("\n== Библиотека на диске, сохранения, Корзина (SPEC §2, §5) ==")
    tmp = tempfile.mkdtemp()
    lib = Path(tmp) / "lib"

    def put(rel, data=b"x", age_days=0):
        p = lib / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    put("new6/ADeckOfHex-v1.15.zip", b"a" * 10)
    put("new6/ADeckOfHex-v1.21.zip", b"b" * 20)
    put("RPG v1.0/www/save/file1.rpgsave", b"OLD1")
    put("RPG v1.0/www/save/file2.rpgsave", b"OLD2")
    put("RPG v1.0/www/game.exe", b"e")
    put("RPG v1.1/www/save/file2.rpgsave", b"NEW2")
    put("RPG v1.1/www/game.exe", b"e2")
    put("Solo v1.0/a.bin")
    put(".hidden/x.bin")
    put("_GameSweep_Trash/skip.bin")
    games = scan_library(str(lib))
    names = sorted(g["name"] for g in games)
    check("auto: new6 раскрыта; скрытые и служебные пропущены",
          names == ["ADeckOfHex-v1.15.zip", "ADeckOfHex-v1.21.zip", "RPG v1.0", "RPG v1.1", "Solo v1.0"], str(names))
    check("flat: new6 — одна игра", "new6" in [g["name"] for g in list_games(str(lib), "flat")])
    check("размер папки = сумма файлов; mtime папки — самый свежий файл",
          next(g for g in games if g["name"] == "RPG v1.0")["size"] == 4 + 4 + 1)
    check("find_saves: save/ и *.rpgsave внутри обёртки", len(find_saves(str(lib / "RPG v1.0"))) >= 1
          and find_saves(str(lib / "Solo v1.0")) == [])

    store = Store(str(lib))
    store.start_scan(str(lib), "auto")
    for _ in range(100):
        st = store.snapshot()
        if st["scanned"] and not st["running"]:
            break
        time.sleep(0.05)
    titles = sorted(g["title"] for g in st["groups"])
    check("Store: найдены группы ADeckOfHex и RPG", titles == ["ADeckOfHex", "RPG"], str(titles))
    check("сводка: 5 игр, 2 группы, 2 старых", st["summary"]["games"] == 5 and st["summary"]["groups"] == 2 and st["summary"]["old"] == 2)
    old_deck, old_rpg = str(lib / "new6" / "ADeckOfHex-v1.15.zip"), str(lib / "RPG v1.0")
    keep_deck = str(lib / "new6" / "ADeckOfHex-v1.21.zip")
    check("trash: «оставить» и чужой путь не трогаются (SPEC §5.2)",
          not any(r["ok"] for r in store.trash([keep_deck, "/etc/passwd"], "ignore")) and os.path.exists(keep_deck))
    check("saves: видны сохранения только у RPG v1.0", list(store.saves([old_deck, old_rpg])) == [old_rpg])
    check("reveal: путь не из списка не открывается", not store.reveal("/etc/passwd") and not store.reveal(str(lib / "нет")))
    r = store.trash([old_rpg], "skip")[0]
    check("saves=skip: игра с сохранениями пропущена, на диске осталась", not r["ok"] and os.path.exists(old_rpg))
    res = store.trash([old_rpg, old_deck], "copy")
    check("saves=copy: старые ушли в корзину", all(x["ok"] for x in res) and not os.path.exists(old_rpg) and not os.path.exists(old_deck))
    check("сохранение скопировано в новую версию, существующее не перезаписано",
          (lib / "RPG v1.1/www/save/file1.rpgsave").read_bytes() == b"OLD1"
          and (lib / "RPG v1.1/www/save/file2.rpgsave").read_bytes() == b"NEW2")
    if not IS_WIN:
        check("корзина (не Windows): файлы в _GameSweep_Trash, не удалены насовсем",
              len(list((lib / "_GameSweep_Trash").glob("*/ADeckOfHex-v1.15.zip"))) == 1)
    check("после удаления групп с несколькими версиями не осталось", store.snapshot()["summary"]["groups"] == 0)

    print("\n== Вкладки (SPEC §8) ==")
    tb = lambda url, title=None: analyze_tab(title or url, url, url)
    F = "https://f95zone.to/threads/"
    t = tb(F + "noir-v0-1-3-bawtsforbrains.318738/")
    check("слаг: noir · 0.1.3", t["names"] == ["noir"] and t["ver"]["text"] == "0.1.3", str(t["names"]))
    t = tb(F + "beyond-worlds-university-v0-9-0a-mister-crowne.282591/")
    check("слаг: beyond worlds university · 0.9.0a", t["names"] == ["beyond worlds university"] and t["ver"]["text"] == "0.9.0a")
    t = tb(F + "dream-team-69-v0-9-0-shodo-games.271262/")
    check("слаг: dream team 69 · 0.9.0 (число в названии не версия)", t["names"] == ["dream team 69"] and t["ver"]["text"] == "0.9.0")
    t = tb("https://allthefallen.moe/forum/index.php?resources/kisaki-another-memory-1-0-0-dixy.9754/")
    check("allthefallen, версия без «v»: kisaki another memory · 1.0.0", t["names"] == ["kisaki another memory"] and t["ver"]["text"] == "1.0.0")
    t = tb(F + "beauties-of-blackfall-demo-flephouse-games.318886/")
    check("слаг без версии: пометка demo, студия остаётся в названии",
          t["ver"] is None and t["flags"] == ["demo"] and t["names"] == ["beauties of blackfall flephouse games"])
    t = tb(F + "some-game-ch2-devname.10/")
    check("слаг: глава ch2 → Ch.2", t["ver"]["text"] == "Ch.2" and t["names"] == ["some game"])
    t = tb(F + "tool-v1-4-0-dev5-someone.20/")
    check("слаг: dev5 после версии — предварительная", t["ver"]["text"] == "1.4.0" and t["ver"]["pre"])
    t = tb("https://f95zone.to/threads/x-y-v1-0-z.5/", "Real Name [v2.5] [SomeDev] | F95zone")
    check("f95: загруженный заголовок важнее слага", t["names"] == ["Real Name"] and t["ver"]["text"] == "2.5" and t["source"] == "заголовок")
    pl = "https://pornolab.net/forum/viewtopic.php?t=777"
    t = tb(pl, "ダンジョンズ / Dungeons And Cat [v1.2.40 + DLC] (Studio / Pub) [uncen] [2026, RPG, Fantasy] [rus] :: PornoLab.Net")
    check("pornolab: латинское название и версия, год/метки не версия", t["names"] == ["Dungeons And Cat"] and t["ver"]["text"] == "1.2.40")
    check("pornolab: заголовок = адрес → названия нет", tb(pl)["names"] == [] and tb(pl)["kind"] == "game")
    check("служебные и прочие: about:, каталог f95, чужой сайт",
          (tb("about:home")["kind"], tb("https://f95zone.to/sam/latest_alpha/")["kind"], tb("https://example.com/x")["kind"]) == ("service", "service", "other"))
    tabs_, dups_ = parse_tabs("[Noir](https://f95zone.to/threads/noir-v0-1-3-x.1/)\nNoir 2 – https://f95zone.to/threads/noir-v0-1-3-x.1/page-3#post-9\nhttps://example.com/a\n\nabout:blank")
    check("форматы строк и дубли по id темы: markdown, «заголовок – адрес», адрес, about:",
          len(tabs_) == 3 and dups_ == 1 and [x["kind"] for x in tabs_] == ["game", "other", "service"])
    mkg = lambda name, tp="folder": {"name": name, "path": "/lib/" + name, "type": tp, "size": 1, "mtime": 1.7e9}
    locs = [mkg("Noir v0.1.1"), mkg("Beyond Worlds University v0.9.0a"), mkg("Dream Team 69 v1.0"), mkg("Kisaki Another Memory"),
            mkg("Dungeons and Cat_v1.2.40.zip", "archive"), mkg("Lust Academy v1.0"), mkg("Beauties of Blackfall")]
    text = "\n".join([F + "noir-v0-1-3-bawtsforbrains.318738/", F + "noir-v0-1-3-bawtsforbrains.318738/page-3#post-1",
                      F + "beyond-worlds-university-v0-9-0a-mister-crowne.282591/", F + "dream-team-69-v0-9-0-shodo-games.271262/",
                      "https://allthefallen.moe/forum/index.php?resources/kisaki-another-memory-1-0-0-dixy.9754/",
                      "[Dungeons And Cat [v1.2.40 + DLC] (Studio) [uncen] [2026, RPG] [rus] :: PornoLab.Net](" + pl + "9)",
                      F + "lust-academy-2-v1-0-somedev.555/", F + "beauties-of-blackfall-demo-flephouse-games.318886/",
                      pl + "1", "about:home", "https://example.com/page"])
    res = analyze_tabs(text, locs)
    vd = {r["name"] or r["url"][-12:]: r["verdict"] for r in res["tabs"] if r["kind"] == "game"}
    want = {"Noir": "update", "Beyond Worlds University": "same", "Dream Team 69": "newer_pc", "Kisaki Another Memory": "unknown_ver",
            "Dungeons And Cat": "same", "Lust Academy 2": "missing", "Beauties Of Blackfall Flephouse Games": "unknown_ver"}
    check("вердикты §8.7: обновить / та же / на ПК новее / не сравнить / нет на ПК",
          all(vd.get(k) == v for k, v in want.items()) and sorted(vd.values()).count("unparsed") == 1, str(vd))
    sm = res["summary"]
    check("сводка: 10 вкладок, 1 дубль, 8 игровых, 1 прочая, 1 служебная, есть на ПК 5, обновить 1",
          (sm["total"], sm["dups"], sm["games"], sm["other"], sm["service"], sm["have"], sm["update"]) == (10, 1, 8, 1, 1, 5, 1), str(sm))
    byname = {r["name"]: r for r in res["tabs"] if r["kind"] == "game" and r["name"]}
    check("«Lust Academy 2» не склеена с «Lust Academy» (лишнее число)", byname["Lust Academy 2"]["local"] is None)
    check("уверенность: длинное точное — да, короткое «noir» — нет, вхождение в 3 слова — да",
          byname["Beyond Worlds University"]["sure"] and not byname["Noir"]["sure"] and byname["Beauties Of Blackfall Flephouse Games"]["sure"])
    check("у найденной игры есть путь и версия на ПК", byname["Noir"]["local"]["path"] == "/lib/Noir v0.1.1" and byname["Noir"]["local"]["version"] == "v0.1.1")
    g2 = index_locals([mkg("Noir v0.1.1"), mkg("Noir v0.3.0"), mkg("Noir v0.2.0")])
    check("несколько версий на ПК: сравнивается новейшая", tab_verdict(tb(F + "noir-v0-3-0-x.1/")["ver"] and tb(F + "noir-v0-3-0-x.1/"), g2["noir"])[0] == "same")
    check("0.9 против 0.10 в вкладках: вердикт есть, но «не уверен»",
          tab_verdict(tb(F + "zed-v0-10-x.2/"), index_locals([mkg("Zed v0.9")])["zed"]) == ("update", False))

    store2 = Store("")
    check("вкладки до сканирования: ответа нет (интерфейс скажет «сначала просканируйте»)", store2.analyze("x") is None)
    store2.games, store2.scanned = locs, True
    data2 = store2.analyze(text)
    check("вкладки после сканирования: тот же результат", bool(data2) and data2["summary"]["update"] == 1)

    print("\n== Поиск в интерфейсе: js/core/search.js (SPEC §6) ==")
    node = shutil.which("node")
    lib_js = Path(__file__).resolve().parent / "js" / "core" / "search.js"
    if not node or not lib_js.exists():
        print("  --   node или search.js не найден — проверка JS пропущена")
    else:
        mod = Path(tmp) / "search.mjs"
        mod.write_text(lib_js.read_text(encoding="utf-8"), encoding="utf-8")
        res = subprocess.run([node, "--check", str(mod)], capture_output=True, text=True)
        check("search.js: синтаксис", res.returncode == 0, res.stderr[:200])
        harness = """import { parseQuery, accepts, highlight } from "./search.mjs";
const A = (q, t, s) => accepts(parseQuery(q), t, s), N = "Slave_Of_Passion_1.0.3_-_Win.zip";
const r = [A("slaveofpassion", N), A("passion slave", N), A("pasion", N), A("ыдфму", N), !A("new6", "G:\\\\PG\\\\new7\\\\Game"),
  A("new6", "G:\\\\PG\\\\new6\\\\Game"), !A("slave -win", N), !A("slave zzzz", N), A(">1мб", N, 5*1048576), !A(">1мб", N, 100), A("1.0.3", N),
  highlight("Slave Of Passion", parseQuery("passion")) === "Slave Of <mark>Passion</mark>", highlight("a<b", parseQuery("zz")) === "a&lt;b"];
console.log(JSON.stringify(r));"""
        f = Path(tmp) / "h.mjs"
        f.write_text(harness, encoding="utf-8")
        res = subprocess.run([node, str(f)], capture_output=True, text=True)
        try:
            flags = json.loads(res.stdout.strip().splitlines()[-1])
        except Exception:
            flags = []
        labels = ["слитно", "порядок слов", "опечатка", "раскладка", "new6≠new7", "new6=new6", "-исключение", "лишнее слово",
                  ">размер", "<размер", "версия 1.0.3", "подсветка", "экранирование HTML"]
        for lab, v in zip(labels, flags):
            check(f"поиск (JS): {lab}", v is True)
        check("поиск (JS): все 13 проверок выполнены", len(flags) == 13, res.stderr[:200])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 60 + f"\n ИТОГО: успешно {ok_n}, ошибок {fail_n}\n" + "=" * 60)
    return 1 if fail_n else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="GameSweep: логика поиска старых версий игр (интерфейс теперь в MediaHub)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    print("GameSweep встроен в MediaHub: раздел «Игры» → «Версии и чистка». Проверка логики: python gamesweep.py --selftest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
