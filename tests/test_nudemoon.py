# Nude-Moon: парсеры на сохранённых страницах (tests/fixtures/nudemoon), загрузка целого комикса без настоящей сети, кодировка windows-1251.
import http.server, json, os, shutil, subprocess, sys, tempfile, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pytest
import engine_nudemoon as N
import enginekit as K
import sites as S

FX = Path(__file__).resolve().parent / "fixtures" / "nudemoon"
NEW = "https://besty.nude-moon.skin/view/14324-i-was-cucked-by-my-girlfriends-dog-mne-nastavila-roga-sobaka-moey-devushki/"
OLD = "https://aqp.nude-moon.skin/34608-femboyteka-cuckets-of-fun--more-rogatogo-veselia.html"
VIEW = "https://aqp.nude-moon.skin/34608-online--femboyteka-cuckets-of-fun--more-rogatogo-veselia.html"


def fx(name): return (FX / name).read_text("utf-8")


# ---------- профиль ----------
def test_profile_slugs_and_urls():
    sl = S.load()
    assert S.manga_title(sl, NEW) == ("https://besty.nude-moon.skin", "nm-view-14324")
    assert S.manga_title(sl, OLD) == S.manga_title(sl, VIEW) == ("https://aqp.nude-moon.skin", "nm-34608")      # страница комикса и просмотр: одна карточка
    assert S.manga_title(sl, "https://aqp.nude-moon.skin/") is None and S.manga_title(sl, "https://aqp.nude-moon.skin/tag/x") is None
    assert S.title_url(sl, NEW + "#comments") == NEW and S.title_url(sl, "https://mangabuff.ru/manga/a/1/2") == "https://mangabuff.ru/manga/a"
    assert all(S.engine_of(S.manga_profile(sl, u)) == "nudemoon" for u in (NEW, OLD))


def test_image_hosts_and_extension_permissions():
    sl = S.load()
    for ok in ("ps1-nudemoon-1xc.cfz.one", "ps3-nd-33.cfz.one", "aqp.nude-moon.skin", "besty.nude-moon.skin"): assert S.manga_img_host_ok(sl, ok), ok
    for bad in ("cfz.one.evil.example", "evilcfz.one", "nude-moon.skin.evil.example"): assert not S.manga_img_host_ok(sl, bad), bad
    perms = json.loads((ROOT / "extension/manifest.json").read_text("utf-8"))["host_permissions"]
    assert "https://*.nude-moon.skin/*" in perms and "https://nude-moon.skin/*" in perms


# ---------- парсеры ----------
def test_parse_new_layout():
    r = N.parse_new(fx("new.html"), NEW)
    assert r["id"] == "view-14324" and r["title"] == "I Was Cucked by My Girlfriend's Dog! / Мне наставила рога собака моей девушки!"
    assert r["cover"] == "https://ps3-nd-33.cfz.one/storage/screens/14000/14324/i.webp" and r["description"] == "NTR C cобачкой заказывали?"
    assert r["authors"] == ["luxsumildo"] and r["translators"] == ["komix"] and r["views"] == "40782" and r["date"].startswith("12 Фев 2024")
    assert len(r["tags"]) == 11 and r["tags"][:3] == ["большие груди", "измена", "без цензуры"]
    p = r["pages"]; assert len(p) == r["expected"] == 27 and len(set(p)) == 27
    assert [int(u.rsplit("/", 1)[1].split(".")[0]) for u in p] == list(range(1, 28))                 # по порядку, хосты CDN разные
    assert len({u.split("/")[2] for u in p}) == 4 and not any("24437" in u for u in p)                  # превью чужих комиксов не попали


def test_parse_old_title_page():
    r = N.parse_old_title(fx("old_title.html"), OLD)
    assert r["id"] == "34608" and r["title"] == "Cuckets of Fun / Море рогатого веселья"
    assert r["authors"] == ["Meesh"] and r["translators"] == ["Фембойтека"] and r["date"] == "12 Ноября 2026" and r["views"] == "9 тыс." and r["expected"] == 9
    assert r["tags"] == ["обычный секс", "фурри", "комикс", "цветная", "подглядывание", "netorare", "x-ray", "без цензуры"]
    assert r["viewer_url"] == VIEW and r["cover"] == "https://aqp.nude-moon.skin/images/thumb/2611/131.jpg"


def test_parse_old_viewer_page():
    r = N.parse_viewer(fx("old_viewer.html"), VIEW)
    assert r["title"] == "Cuckets of Fun / Море рогатого веселья" and len(r["pages"]) == 9
    assert r["pages"][0] == "https://aqp.nude-moon.skin/manga/2026/11/131-femboyteka-cuckets-of-fun--more-rogatogo-veselia/1.jpg" and r["pages"][8].endswith("/9.jpg")


def test_layout_detection():
    assert [N.layout_of(fx(f)) for f in ("new.html", "old_title.html", "old_viewer.html")] == ["new", "old", "viewer"]
    assert N.layout_of("<html>не комикс</html>") == ""


# ---------- загрузка комикса ----------
def serve(**pages):
    calls = []
    def get(url):
        calls.append(url)
        return pages.get(url, "")
    get.calls = calls; return get


def test_load_comic_all_three_entry_points():
    r = N.load_comic(serve(**{NEW: fx("new.html")}), NEW)
    assert len(r["pages"]) == 27 and r["warn"] == "" and r["source"] == NEW
    g = serve(**{OLD: fx("old_title.html"), VIEW: fx("old_viewer.html")})                                # со страницы комикса идём на «Читать онлайн»
    r = N.load_comic(g, OLD); assert g.calls == [OLD, VIEW] and len(r["pages"]) == 9 and r["tags"][0] == "обычный секс" and r["id"] == "34608"
    r = N.load_comic(serve(**{VIEW: fx("old_viewer.html")}), VIEW); assert len(r["pages"]) == 9 and r["tags"] == []   # просмотр без страницы комикса: теги неизвестны


def test_load_comic_reports_mismatch_and_clear_errors():
    html = fx("new.html").replace("</i>27</div>", "</i>30</div>").replace('><span class="fal fa-camera"></span>27<', '><span class="fal fa-camera"></span>30<')
    r = N.load_comic(serve(**{NEW: html}), NEW); assert r["expected"] == 30 and "найдено 27" in r["warn"] and "30" in r["warn"]
    for bad, text in ((lambda u: "<title>Just a moment...</title>", "проверки браузера"), (lambda u: "", "проверки браузера"),
                      (lambda u: '<meta property="og:title" content="x"><p>не комикс</p>', "вёрстку"),
                      (lambda u: '<meta property="og:title" content="x"><div class="page__player"></div>', "ни одной страницы")):
        with pytest.raises(K.EngineError) as e: N.load_comic(bad, NEW)
        assert text in str(e.value)
    no_link = fx("old_title.html").replace("-online--", "-x--")
    with pytest.raises(K.EngineError) as e: N.load_comic(serve(**{OLD: no_link}), OLD)
    assert "Читать онлайн" in str(e.value)
    with pytest.raises(K.EngineError): N.load_comic(serve(**{OLD: fx("old_title.html"), VIEW: "<title>Just a moment...</title>"}), OLD)


def test_decode_html_prefers_header_then_utf8_then_cp1251():
    ru = "Море рогатого веселья"
    assert K.decode_html(ru.encode("cp1251"), "windows-1251") == ru and K.decode_html(ru.encode("utf-8")) == ru and K.decode_html(ru.encode("cp1251")) == ru
    assert K.decode_html(ru.encode("cp1251"), "nonsense-charset") == ru       # неизвестное имя кодировки не ломает чтение


# ---------- сквозная загрузка ----------
DRIVER = r'''
import json, sys, sqlite3
sys.path.insert(0, ".")
import app
FIX = json.load(open("fix.json", encoding="utf-8")); calls = []
app.ext_online = lambda: True
app.fetch_html = lambda url, job=None: (calls.append(url), FIX.get(url, ""))[1]
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
class FakeFast:
    def __init__(self, *a, **k): self.a = a
    def get(self, u): return JPG
app.Fast = FakeFast; app.time.sleep = lambda s: None
url = sys.argv[1]; run = app.by_engine(lambda j: None)
job = {"id": 1, "url": url, "kind": "mangaurl", "first": 0, "last": 0, "cancel": False, "title": "", "pct": 0, "eta": 0, "speed": 0}
run(job)
con = sqlite3.connect("library.db"); con.row_factory = sqlite3.Row; row = dict(con.execute("select * from items where kind='manga' order by id desc").fetchone()); con.close()
print("RESULT" + json.dumps({"final": job["final"], "calls": calls, "extra": app.manga_extra(row), "author": row["author"], "key": row["url"], "info": app.manga_info(row["id"])}, ensure_ascii=False))
'''


def _copy_project(tmp, fix):
    skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
    for e in ROOT.iterdir():
        if e.name in skip or e.suffix == ".zip": continue
        shutil.copytree(e, tmp / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, tmp / e.name)
    (tmp / "settings.json").write_text(json.dumps({"folder": str(tmp / "dl"), "games_root": ""}), "utf-8")
    (tmp / "fix.json").write_text(json.dumps(fix, ensure_ascii=False), "utf-8"); (tmp / "driver.py").write_text(DRIVER, "utf-8")


def _run(tmp, url):
    p = subprocess.run([sys.executable, "driver.py", url], cwd=tmp, capture_output=True, text=True, timeout=120, env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1"))
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, p.stdout[-800:] + p.stderr[-1500:]
    return json.loads(line[6:])


@pytest.mark.parametrize("url,fix,pages,key", [
    (NEW, {NEW: fx("new.html")}, 27, "manga:nm-view-14324"),
    (OLD, {OLD: fx("old_title.html"), VIEW: fx("old_viewer.html")}, 9, "manga:nm-34608"),
])
def test_downloads_whole_comic_as_one_chapter_and_skips_on_repeat(url, fix, pages, key):
    tmp = Path(tempfile.mkdtemp(prefix="mh-nm-"))
    try:
        _copy_project(tmp, fix); r = _run(tmp, url)
        assert r["final"] == f"готово: {pages} стр." and r["author"] == "Nude-Moon" and r["key"] == key, r
        man = json.loads(next((tmp / "dl" / "Manga").glob("*/manifest.json")).read_text("utf-8"))
        assert man["listed"] == [{"cid": "1", "label": "Целиком"}] and set(man["chapters"]) == {"1"}
        ch = man["chapters"]["1"]; assert ch["done"] and len(ch["files"]) == pages and ch["label"] == "Целиком"
        assert man["meta"]["tags"] and man["meta"]["source"] == url and man["cover"].endswith((".jpg", ".png", ".webp"))
        assert r["extra"].startswith("1 из 1 гл. · ") and r["info"]["meta"]["tags"] == man["meta"]["tags"]    # теги видны на карточке и в сведениях
        r2 = _run(tmp, url); assert r2["final"] == "уже скачано", r2
    finally: shutil.rmtree(tmp, ignore_errors=True)


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = "<html>Море рогатого веселья</html>".encode("cp1251")
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=windows-1251"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def test_direct_fetch_decodes_windows_1251_page():
    tmp = Path(tempfile.mkdtemp(prefix="mh-nm2-")); srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _copy_project(tmp, {})
        (tmp / "driver.py").write_text(f'import sys; sys.path.insert(0, "."); import app; print("RESULT" + app.http_html("http://127.0.0.1:{srv.server_port}/x"))', "utf-8")
        p = subprocess.run([sys.executable, "driver.py"], cwd=tmp, capture_output=True, text=True, timeout=60, env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1", MEDIAHUB_TEST_ALLOW_LOCAL="1"))
        assert "RESULT<html>Море рогатого веселья</html>" in p.stdout, p.stdout + p.stderr[-800:]
    finally:
        srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
