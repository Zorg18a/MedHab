# mangabuff.ru: парсеры на сохранённых страницах сайта (tests/fixtures/mangabuff) и сквозная загрузка без настоящей сети.
import http.server, json, os, shutil, subprocess, sys, tempfile, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pytest
import engine_mangabuff as E
import sites as S

FX = Path(__file__).resolve().parent / "fixtures" / "mangabuff"
SLUG = "zhena-zhdala-v-pshenichnom-pole"
SITE = "https://mangabuff.ru"
TITLE_URL = f"{SITE}/manga/{SLUG}"


def title_html(): return (FX / "title.html").read_text("utf-8")
def chapter_html(): return (FX / "chapter.html").read_text("utf-8")


# ---------- профиль ----------
def test_profile_and_links():
    sl = S.load()
    assert S.engine_of(S.manga_profile(sl, TITLE_URL)) == "mangabuff" and S.engine_of(S.manga_profile(sl, "https://senkuro.me/manga/a")) == "senkuro"
    assert S.manga_title(sl, f"{TITLE_URL}/1/36") == (SITE, SLUG)            # ссылка на главу ведёт к тайтлу
    assert S.manga_title(sl, "https://www.mangabuff.ru/manga/a_b-1") == (SITE, "a_b-1")
    assert S.manga_img_host_ok(sl, "c3.mangabuff.ru") and not S.manga_img_host_ok(sl, "c3.mangabuff.ru.evil.example")
    assert S.manga_profile(sl, "https://mangabuff.ru/genres/x") is None


def test_env_mirror_can_name_engine():
    sl = S.with_extra_manga(S.load(), ["mirror.example=mangabuff", "other.example"])
    assert S.engine_of(S.manga_profile(sl, "https://mirror.example/manga/a")) == "mangabuff"
    assert S.engine_of(S.manga_profile(sl, "https://other.example/manga/a")) == "senkuro"


# ---------- парсеры ----------
def test_parse_title():
    t = E.parse_title(title_html(), TITLE_URL)
    assert t["slug"] == SLUG and t["title"] == "Жена ждала в пшеничном поле"
    assert t["cover"] == f"{SITE}/img/manga/posters/{SLUG}.jpg"
    assert t["description"].startswith("Это был брак по расчёту") and "Повседневность" in t["genres"] and len(t["genres"]) == 9
    ch = t["chapters"]; assert len(ch) == 36 and len({c["cid"] for c in ch}) == 36
    assert ch[0] == {"cid": "1-36", "vol": "1", "num": "36", "url": f"{TITLE_URL}/1/36", "date": "07.11.2026", "label": "Том 1 Глава 36"}
    assert ch[-1]["cid"] == "1-1" and ch[-1]["date"] == "16.06.2026"          # порядок сайта: новые первыми


def test_parse_title_ignores_foreign_links_and_keeps_decimal_chapters():
    html = (f'<meta property="og:url" content="{TITLE_URL}"><h1 class="manga__name">T</h1>'
            f'<a href="{TITLE_URL}/2/10.5" class="chapters__item"><div class="chapters__volume">Том <span>2</span></div><div class="chapters__name">Бонус</div></a>'
            f'<a href="{SITE}/manga/other-title/1/1" class="chapters__item"></a><a href="{TITLE_URL}/2/10.5" class="chapters__item"></a>'
            f'<a href="{SITE}/user/1" class="chapters__item"></a>')
    ch = E.parse_title(html, TITLE_URL)["chapters"]
    assert [(c["cid"], c["label"]) for c in ch] == [("2-10.5", "Том 2 Глава 10.5 Бонус")]   # чужой тайтл, не глава и повтор отброшены


def test_parse_chapter_lazy_and_eager_images_in_order():
    r = E.parse_chapter(chapter_html(), f"{TITLE_URL}/1/36")
    p = r["pages"]; assert len(p) == 13 and r["servers"] == [1, 3] and r["slug"] == SLUG
    assert all(u.startswith(f"https://c3.mangabuff.ru/chapters/{SLUG}/1/36/") for u in p)
    assert [int(u.rsplit("/", 1)[1].split("-")[0]) for u in p] == list(range(1, 14))      # src у первых, data-src у остальных
    assert len(set(p)) == 13


def test_parse_chapter_sorts_by_data_page_resolves_relative_and_skips_placeholders():
    html = ('<div class="reader__item" data-page="2"><img src="/chapters/s/1/1/2-b.jpg"></div>'
            '<div class="reader__item" data-page="1"><img src="data:image/gif;base64,AAAA" data-src="/chapters/s/1/1/1-a.jpg"></div>'
            '<div class="reader__item" data-page="3"><img src="data:image/gif;base64,AAAA"></div>')
    assert E.parse_chapter(html, f"{TITLE_URL}/1/1")["pages"] == [f"{SITE}/chapters/s/1/1/1-a.jpg", f"{SITE}/chapters/s/1/1/2-b.jpg"]


def test_blocked_and_empty_pages_give_clear_errors():
    assert E.looks_blocked("<title>Just a moment...</title>") and E.looks_blocked("") and not E.looks_blocked(title_html())
    with pytest.raises(E.EngineError): E.load_title(lambda u: "<title>Just a moment...</title>", SITE, SLUG)
    with pytest.raises(E.EngineError): E.load_title(lambda u: '<meta property="og:title" content="x">', SITE, SLUG)       # нет глав
    with pytest.raises(E.EngineError): E.load_pages(lambda u: '<meta property="og:title" content="x">', {"url": f"{TITLE_URL}/1/1"})   # нет страниц


# ---------- сквозная загрузка ----------
DRIVER = r'''
import json, sys, time
sys.path.insert(0, ".")
import app
mode = sys.argv[1]
FIX = json.load(open("fix.json", encoding="utf-8")); calls = []
app.ext_online = lambda: True
def fake_html(url, job=None):
    calls.append(url)
    if mode == "run1" and url.endswith("/1/35"): return ""          # глава 35 в первый раз не открылась
    return FIX["title"] if url.count("/") == 4 else FIX["chapter"]
app.fetch_html = fake_html
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
class FakeFast:
    def __init__(self, *a, **k): pass
    def get(self, u): return JPG
app.Fast = FakeFast; app.time.sleep = lambda s: None
job = {"id": 1, "url": "https://mangabuff.ru/manga/%s/1/36", "kind": "mangaurl", "first": 34, "last": 36, "cancel": False, "title": "", "pct": 0, "eta": 0, "speed": 0}
app.manga_http(job)
print("RESULT" + json.dumps({"final": job["final"], "calls": calls, "pct": job["pct"]}, ensure_ascii=False))
''' % SLUG


def _project_copy(tmp):
    skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
    for e in ROOT.iterdir():
        if e.name in skip or e.suffix == ".zip": continue
        shutil.copytree(e, tmp / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, tmp / e.name)
    (tmp / "settings.json").write_text(json.dumps({"folder": str(tmp / "dl"), "games_root": ""}), "utf-8")
    (tmp / "fix.json").write_text(json.dumps({"title": title_html(), "chapter": chapter_html()}, ensure_ascii=False), "utf-8")
    (tmp / "driver.py").write_text(DRIVER, "utf-8")


def _run(tmp, mode):
    p = subprocess.run([sys.executable, "driver.py", mode], cwd=tmp, capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1"))
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, p.stdout[-800:] + p.stderr[-1500:]
    return json.loads(line[6:])


def test_manga_http_downloads_resumes_and_reports_failures():
    tmp = Path(tempfile.mkdtemp(prefix="mh-mb-"))
    try:
        _project_copy(tmp)
        r1 = _run(tmp, "run1")
        assert r1["final"].startswith("частично: 2 из 3 глав") and "Том 1 Глава 35" in r1["final"], r1
        folder = tmp / "dl" / "Manga" / "Жена ждала в пшеничном поле"; man = json.loads((folder / "manifest.json").read_text("utf-8"))
        assert [c["cid"] for c in man["listed"]][:2] == ["1-1", "1-2"] and len(man["listed"]) == 36      # от первой главы к последней
        assert set(man["chapters"]) == {"1-34", "1-36"} and all(c["done"] and len(c["files"]) == 13 for c in man["chapters"].values())
        assert man["cover"].endswith(".jpg") and (folder / "chapters" / "1-36" / "013.jpg").exists()
        import sqlite3
        con = sqlite3.connect(tmp / "library.db"); row = con.execute("select title,author,kind,url from items where kind='manga'").fetchone(); con.close()
        assert row == ("Жена ждала в пшеничном поле", "MangaBuff", "manga", "manga:" + SLUG)
        r2 = _run(tmp, "run2")                                                                              # повтор: готовые главы не трогаем
        assert r2["final"] == "готово: 3 из 3 глав.", r2
        assert not [u for u in r2["calls"] if u.endswith(("/1/34", "/1/36"))] and any(u.endswith("/1/35") for u in r2["calls"])
        assert set(json.loads((folder / "manifest.json").read_text("utf-8"))["chapters"]) == {"1-34", "1-35", "1-36"}
    finally: shutil.rmtree(tmp, ignore_errors=True)


DISPATCH = r'''
import sys; sys.path.insert(0, ".")
import app
seen = []
run = app.by_engine(lambda j: seen.append("senkuro"))
app.manga_http = lambda j: seen.append("mangabuff")
run = app.by_engine(lambda j: seen.append("senkuro"))
for u in ("https://mangabuff.ru/manga/a/1/2", "https://senkuro.me/manga/a", "https://ne.senkognito.com/manga/b"): run({"url": u})
print("RESULT" + ",".join(seen))
'''


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code, body = (403, b"<title>Just a moment...</title>") if self.path == "/blocked" else (200, "<html>привет</html>".encode())
        self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def test_engine_dispatch_and_direct_http_fetch():
    tmp = Path(tempfile.mkdtemp(prefix="mh-mb2-")); srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _project_copy(tmp)
        (tmp / "driver.py").write_text(DISPATCH + f'''
print("HTTP" + app.http_html("http://127.0.0.1:{srv.server_port}/ok"))
print("HTTP" + app.http_html("http://127.0.0.1:{srv.server_port}/blocked"))
print("BLK" + str(app.engine_mangabuff.looks_blocked(app.http_html("http://127.0.0.1:{srv.server_port}/blocked"))))
''', "utf-8")
        p = subprocess.run([sys.executable, "driver.py"], cwd=tmp, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1", MEDIAHUB_TEST_ALLOW_LOCAL="1"))
        out = p.stdout.splitlines(); assert "RESULTmangabuff,senkuro,senkuro" in out, p.stdout + p.stderr[-1200:]
        assert "HTTP<html>привет</html>" in out and "HTTP<title>Just a moment...</title>" in out and "BLKTrue" in out
    finally:
        srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
