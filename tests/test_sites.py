# Единый список сайтов (sites.json): проверка профилей, актуальность расширения и совпадение определения типа в app.py и в расширении.
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import pytest
import sites as S
import gen_sites
from test_game_find import jget, jpost

# (адрес, тип в app.py, тип в расширении)
TABLE = [
    ("https://senkuro.me/manga/abc-1", "manga", "manga"),
    ("https://www.senkuro.me/manga/abc", "manga", "manga"),
    ("https://ne.senkognito.com/manga/x-y", "manga", "manga"),
    ("https://mangabuff.ru/manga/zhena-zhdala-v-pshenichnom-pole", "manga", "manga"),
    ("https://mangabuff.ru/manga/zhena-zhdala-v-pshenichnom-pole/1/36", "manga", "manga"),
    ("https://mangabuff.ru/genres/romantika-manga", "unknown", "other"),
    ("https://pornolab.net/forum/viewtopic.php?t=3282477", "game", "game"),
    ("https://pornolab.net/forum/index.php", "unknown", "other"),
    ("https://byrutgame.org/50942-aniwars-call-of-the-void.html", "game", "game"),
    ("https://byrutgame.org/", "unknown", "other"),
    ("https://aqp.nude-moon.skin/34608-femboyteka-cuckets-of-fun--more-rogatogo-veselia.html", "manga", "manga"),
    ("https://senkuro.me/", "unknown", "other"),
    ("https://senkuro.me/manga/", "unknown", "other"),
    ("https://vimeo.com/123", "video", "video"),
    ("https://soundcloud.com/a/b", "audio", "audio"),
    ("https://artist.bandcamp.com/album/x", "audio", "audio"),
    ("https://notbandcamp.com/x", "unknown", "other"),
    ("https://f95zone.to/threads/foo.123/", "game", "game"),
    ("https://f95zone.to/forums/", "unknown", "other"),
    ("https://store.steampowered.com/app/1", "game", "game"),
    ("https://x.itch.io/g", "game", "game"),
    ("https://music.youtube.com/watch?v=1", "audio", "audio"),
    ("https://youtu.be/abc", "video", "video"),
    ("https://example.org/page", "unknown", "other"),
]


def test_profiles_are_valid_and_cover_all_kinds():
    sl = S.load(); assert {s["kind"] for s in sl} == set(S.KINDS)
    assert "senkuro.me" in S.manga_hosts(sl) and "ne.senkognito.com" in S.manga_hosts(sl)


@pytest.mark.parametrize("bad", [
    {"id": "a", "kind": "manga", "hosts": ["x.me"]},                                          # у манги нет path
    {"id": "a", "kind": "manga", "hosts": ["x.me"], "path": "^/m/(a)(b)"},                  # две группы
    {"id": "a", "kind": "video", "hosts": ["WWW.x.me"]},                                      # регистр и www
    {"id": "a", "kind": "video", "hosts": ["x.me"], "path": "^/("},                          # не регулярка
    {"id": "a", "kind": "video", "hosts": ["x.me"], "path": "/threads"},                     # без ^
    {"id": "a", "kind": "video", "hosts": ["x.me"], "suffixes": ["x.me"]},                   # без точки
    {"id": "a", "kind": "video", "hosts": ["x.me"], "oops": 1},                               # неизвестное поле
    {"id": "a", "kind": "comics", "hosts": ["x.me"]},                                         # неизвестный тип
    {"id": "", "kind": "video", "hosts": ["x.me"]},
])
def test_invalid_profiles_are_rejected(bad):
    with pytest.raises(ValueError): S.validate([bad])


def test_duplicate_ids_rejected():
    p = {"id": "a", "kind": "video", "hosts": ["x.me"]}
    with pytest.raises(ValueError): S.validate([p, dict(p)])


def test_generated_extension_files_are_up_to_date():
    for rel, text in gen_sites.expected().items():
        assert (ROOT / rel).read_text("utf-8") == text, f"{rel} устарел: python tools/gen_sites.py"


def test_manifest_permissions_match_profiles():
    perms = json.loads((ROOT / "extension/manifest.json").read_text("utf-8"))["host_permissions"]
    want = {f"https://{h}/*" for s in S.load() if s.get("permission") for h in s["hosts"]} | {f"https://*{x}/*" for s in S.load() if s.get("permission") for x in s.get("suffixes", [])}
    assert set(perms) - {"http://127.0.0.1:8765/*"} == want


def test_env_mirrors_become_manga_hosts():
    sl = S.with_extra_manga(S.load(), ["mirror.example", "", "SENKURO.ME", "mirror.example"])
    assert S.manga_hosts(sl).count("mirror.example") == 1 and S.manga_title(sl, "https://mirror.example/manga/a-b") == ("https://mirror.example", "a-b")
    assert S.manga_title(S.load(), "https://mirror.example/manga/a-b") is None
    assert S.manga_title(sl, "ftp://senkuro.me/manga/a") is None


def test_manga_image_hosts():
    sl = S.load()
    for ok in ("senkuro.me", "cdn.senkuro.me", "mirai.senkuro.net", "ne.senkognito.com", "img.senkognito.com"):
        assert S.manga_img_host_ok(sl, ok), ok
    for bad in ("evil.example", "senkuro.me.evil.example", "notsenkuro.net", ""):
        assert not S.manga_img_host_ok(sl, bad), bad


def _paired(server, origin="chrome-extension://sitestest"):
    """Сопряжение расширения так же, как у человека: hello → согласие в приложении → hello с выдачей токена."""
    h = {"Origin": origin}
    assert json.loads(server.post("/ext/hello", {"name": "test"}, h)[2])["status"] == "pending"
    assert jpost(server, "/api/ext/approve", {"origin": origin, "allow": True})["ok"]
    t = json.loads(server.post("/ext/hello", {"name": "test"}, h)[2]); assert t["status"] == "ok"
    return {"Origin": origin, "X-MH-Token": t["token"]}


def test_app_classifies_like_table(server):
    server.reset(); hdr = _paired(server)
    try:
        tabs = [{"id": i, "windowId": 1, "url": u, "title": u} for i, (u, _, _) in enumerate(TABLE)]
        r = json.loads(server.post("/ext/tabs", {"tabs": tabs, "browser": "chrome"}, hdr)[2]); assert r["count"] == len(TABLE), r
        rows = [x for b in jget(server, "/api/inbox")["batches"] for x in b.get("rows", b.get("items", []))]
        got = {x["url"]: x["kind"] for x in rows}
        assert len(got) == len(TABLE), got
        for u, k, _ in TABLE: assert got[u] == k, (u, got[u], k)
    finally: jpost(server, "/api/ext/forget", {"origin": hdr["Origin"]})


def test_extension_classifies_like_table(page):
    page.goto("about:blank")
    page.add_script_tag(path=str(ROOT / "extension/sites.js")); page.add_script_tag(path=str(ROOT / "extension/kind.js"))
    for u, _, k in TABLE: assert page.evaluate("u => kindOf(u)", u) == k, u
    assert page.evaluate("kindOf('не адрес')") == "other"


def test_sites_api_lists_manga_hosts(server):
    assert {"senkuro.me", "ne.senkognito.com"} <= set(jget(server, "/api/sites")["manga"])
