import http.client, os, re, shutil, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, json, itertools
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import write_wav, write_png

ROOT = Path(__file__).resolve().parent.parent
AXE = ROOT / "tests" / "vendor" / "axe.min.js"
_n = itertools.count(1)


class Server:
    def __init__(self, proc, port, base):
        self.proc, self.port, self.base = proc, port, base
        self.url = f"http://127.0.0.1:{port}"

    def reset(self):
        con = sqlite3.connect(self.base / "library.db", timeout=10)
        con.execute("delete from items"); con.execute("delete from progress")
        for t in ("playpos", "feed", "watch"):            # лента и отслеживаемые каналы тоже не должны переходить из теста в тест
            try: con.execute(f"delete from {t}")
            except sqlite3.OperationalError: pass
        con.commit(); con.close()

    # --- HTTP без браузера (этап 2) ---
    def _req(self, method, path, body=None, headers=None):
        h = {"X-MH": "1"} if method == "POST" else {}
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = None if body is None else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode("utf-8")
        hh = {k: v for k, v in h.items() if v != ""}
        c.request(method, path, body=data, headers=hh); r = c.getresponse(); b = r.read()
        out = (r.status, {k: v for k, v in r.getheaders()}, b); c.close(); return out

    def get(self, path, headers=None): return self._req("GET", path, None, headers)
    def post(self, path, body, headers=None): return self._req("POST", path, body, headers)

    def _sql(self, q, a=()):
        con = sqlite3.connect(self.base / "library.db", timeout=10)
        try:
            cur = con.execute(q, a); con.commit(); return cur
        finally: con.close()

    def _playpos_rows(self, item_id):
        con = sqlite3.connect(self.base / "library.db", timeout=10)
        try: return con.execute("select count(*) from playpos where item_id=?", (item_id,)).fetchone()[0]
        except sqlite3.OperationalError: return 0
        finally: con.close()

    def media_dir(self, item_id):
        con = sqlite3.connect(self.base / "library.db", timeout=10)
        try: return Path(con.execute("select path from items where id=?", (item_id,)).fetchone()[0]).parent
        finally: con.close()

    def add_media(self, title, kind="audio", seconds=2, ext=".wav", raw=None, subs=None, thumb=False, into=None):
        n = next(_n); safe = re.sub(r'[\\/:*?"<>|]+', "_", title)[:40] or "media"
        d = Path(into) if into else self.base / "media" / str(n); path = d / (safe + ext)
        if raw is not None: d.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        else: write_wav(path, seconds)
        for suffix, data in (subs or {}).items(): (d / f"{path.stem}.{suffix}").write_bytes(data)
        tp = str(write_png(d / (safe + ".png"), 64, 36)) if thumb else ""
        cur = self._sql("insert into items(title,author,topic,kind,path,root,url,size,thumb) values(?,?,?,?,?,?,?,?,?)",
                        (title, "", "", kind, str(path), "", f"test://m{n}", path.stat().st_size, tp))
        return cur.lastrowid

    def add_manga(self, title, chapters=3, pages=2, missing=(), progress=None, updated=None, manifest=True):
        n = next(_n); slug = f"t{n}"; root = self.base / "manga" / slug; root.mkdir(parents=True, exist_ok=True)
        listed, chs = [], {}
        for k in range(chapters):
            cid = str(100 + k); listed.append({"cid": cid, "label": f"Глава {k + 1}"})
            if k in missing: continue
            files = []
            for p in range(pages):
                f = f"{p + 1:03d}.png"; write_png(root / "chapters" / cid / f, 800, 1200); files.append(f)
            chs[cid] = {"label": f"Глава {k + 1}", "expected": pages, "files": files, "done": True}
        if manifest: (root / "manifest.json").write_text(json.dumps({"slug": slug, "title": title, "cover": "", "listed": listed, "chapters": chs}, ensure_ascii=False), "utf-8")
        cur = self._sql("insert into items(title,author,topic,kind,path,root,url,size,thumb) values(?,?,?,?,?,?,?,?,?)",
                        (title, "Senkuro", "Манга", "manga", str(root), str(root), "manga:" + slug, 0, ""))
        if progress is not None:
            ci, pg = progress; cid = str(100 + ci)
            con = sqlite3.connect(self.base / "library.db", timeout=10)
            try: con.execute("alter table progress add column updated real")
            except sqlite3.OperationalError: pass
            con.execute("insert or replace into progress(slug,cid,page,updated) values(?,?,?,?)", (slug, cid, pg, updated)); con.commit(); con.close()
        return cur.lastrowid

    def set_pos(self, item_id, pos, dur, updated=None):
        self._sql("create table if not exists playpos(item_id integer primary key, pos real not null, dur real not null default 0, updated real not null)")
        self._sql("insert or replace into playpos(item_id,pos,dur,updated) values(?,?,?,?)", (item_id, pos, dur, time.time() if updated is None else updated))

    def add_item(self, title, kind, info=None):
        cols = dict(title=title, author="", topic="", kind=kind, path=str(self.base / "x" / title[:8].replace('"', "_").replace("/", "_")),
                    root=str(self.base / "x"), url=f"test://{next(_n)}", size=0)
        con = sqlite3.connect(self.base / "library.db", timeout=10)
        if kind == "game":
            try: con.execute("alter table items add column info")
            except sqlite3.OperationalError: pass
            cols["info"] = json.dumps(info or {"name": title})
        cur = con.execute(f"insert into items({','.join(cols)}) values({','.join('?' * len(cols))})", list(cols.values()))
        con.commit(); i = cur.lastrowid; con.close(); return i


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="session")
def server():
    base = Path(tempfile.mkdtemp(prefix="mh-test-"))
    skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
    for e in ROOT.iterdir():
        if e.name in skip or e.suffix == ".zip": continue
        shutil.copytree(e, base / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, base / e.name)
    (base / "settings.json").write_text(json.dumps({"folder": str(base / "dl"), "games_root": ""}), "utf-8")
    port = _free_port()
    env = dict(os.environ, MEDIAHUB_PORT=str(port), MEDIAHUB_NO_BROWSER="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=base, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1); break
        except Exception: time.sleep(0.2)
    else:
        proc.kill(); raise RuntimeError("server did not start")
    yield Server(proc, port, base)
    proc.kill(); shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"]); yield b; b.close()


@pytest.fixture
def page(browser, server):
    server.reset()
    ctx = browser.new_context(); ctx.set_default_timeout(5000); pg = ctx.new_page(); yield pg; ctx.close()


@pytest.fixture
def touch_page(browser, server):
    server.reset()
    ctx = browser.new_context(has_touch=True, is_mobile=True); ctx.set_default_timeout(5000); pg = ctx.new_page(); yield pg; ctx.close()


@pytest.fixture(autouse=True)
def _fresh_db(request):
    """Строки БД копятся в сессионном сервере: любой тест с `server` начинает с чистой БД."""
    if "server" in request.fixturenames: request.getfixturevalue("server").reset()


def open_player(page, server, item_id):
    page.goto(f"{server.url}/p/{item_id}")
    page.wait_for_function("() => { const m = document.getElementById('m'); return !!m && m.readyState >= 1 && m.dataset.ready === '1' }")


def open_view(page, server, view):
    page.goto(f"{server.url}/#{view}"); page.wait_for_load_state("networkidle")


def set_prefs(page, **prefs):
    page.add_init_script(f"localStorage.setItem('mh.prefs', JSON.stringify({json.dumps(prefs)}))")


def run_axe(page):
    if not AXE.exists(): pytest.skip("tests/vendor/axe.min.js missing")
    page.add_script_tag(content=AXE.read_text("utf-8"))
    res = page.evaluate("axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})))")
    return [v for v in res if v["impact"] in ("serious", "critical")]


def stub_inbox(page, titles):
    rows = [{"id": i + 1, "status": "pending", "kind": "video", "url": f"https://example.com/{i}", "title": t, "host": "example.com",
             "state": "new", "state_text": "новое", "action": "download", "close": True, "fate": ""} for i, t in enumerate(titles)]
    body = {"batches": [{"batch": 1, "pending": True, "created": "2026-11-08 10:00:00", "rows": rows}]}
    page.route("**/api/inbox", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)))


VIEWS = ["library", "inbox", "downloads", "games", "settings"]
_READY = {"library": ".cv", "inbox": ".ir", "downloads": ".job", "games": "[data-card]", "settings": "#d_keys"}


PAGES = ["player", "reader"]          # отдельные страницы этапа 2: /p/<id> и /m/<id>
ALL_VIEWS = VIEWS + PAGES
_SUB = "1\n00:00:01,000 --> 00:00:02,000\nПривет, мир\n".encode("utf-8")


def open_any(page, server, view):
    """Раздел индекса с данными либо страница плеера (с возобновлением и субтитрами) или читалки (с прогрессом)."""
    if view == "player":
        i = server.add_media("Лекция по физике", "video", seconds=60, subs={"ru.srt": _SUB, "en.srt": _SUB}); server.set_pos(i, 30, 60)
        open_player(page, server, i); page.wait_for_timeout(200)
    elif view == "reader":
        i = server.add_manga("Манга Один", chapters=3, pages=3, progress=(0, 1))
        page.goto(f"{server.url}/m/{i}"); page.wait_for_selector("#v img"); page.wait_for_timeout(300)
    else:
        open_seeded(page, server, view)


def open_seeded(page, server, view):
    """Раздел с данными: библиотека, игры, список загрузок и входящие подставляются."""
    for t, k in (("Лекция по физике", "video"), ("Манга Один", "manga"), ("Игра Тест", "game")):
        iid = server.add_item(title=t, kind=k)
        if k == "video": server.set_pos(iid, 30, 600)      # в Библиотеке виден блок «Продолжить»
    jobs = [{"id": 1, "title": "Лекция по физике: часть 1", "kind": "video", "status": "качается", "pct": 42, "speed": 2500000, "eta": 95},
            {"id": 2, "title": "Плейлист", "kind": "audio", "status": "в очереди", "pct": 0},
            {"id": 3, "title": "Манга Один", "kind": "manga", "status": "готово", "pct": 100}]
    page.route("**/api/jobs", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(jobs)))
    stub_inbox(page, ["Лекция по физике", "Плейлист с музыкой"])
    page.goto(f"{server.url}/#{view}")
    page.wait_for_selector(_READY[view])
    page.wait_for_timeout(300)
