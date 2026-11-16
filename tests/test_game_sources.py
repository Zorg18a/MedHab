# Источники игр: pornolab и Byrutor рядом с F95zone. Парсеры на сохранённых страницах (tests/fixtures/games), сборки в одной карточке, проверка версий.
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pytest
import engine_games as G
import sites as S

FX = Path(__file__).resolve().parent / "fixtures" / "games"
WITCH = "https://pornolab.net/forum/viewtopic.php?t=3282477"
SHINOBI = "https://pornolab.net/forum/viewtopic.php?t=3039092"
SUZUKA = "https://pornolab.net/forum/viewtopic.php?t=3279944"
BYRUT = "https://byrutgame.org/50942-aniwars-call-of-the-void.html"


def fx(n): return (FX / n).read_text("utf-8")


# ---------- профили ----------
def test_profiles_and_keys():
    sl = S.load()
    for u, eng in ((WITCH, "pornolab"), (BYRUT, "byrutor"), ("https://f95zone.to/threads/x.1/", "f95"), ("https://store.steampowered.com/app/1", "f95")):
        p = S.match(sl, S.host_of(u), __import__("urllib.parse").parse.urlparse(u).path, ("game",)); assert S.engine_of(p) == eng, u
    assert S.match(sl, "pornolab.net", "/forum/index.php", ("game",)) is None and S.match(sl, "byrutgame.org", "/", ("game",)) is None
    assert G.source_key("pornolab", WITCH + "&start=30#p5") == WITCH and G.source_key("byrutor", BYRUT + "?x=1#c") == BYRUT


# ---------- pornolab ----------
def test_pornolab_witch_has_russian_tags_cover_torrent_size():
    m = G.parse_pornolab(fx("pornolab_witch.html"), WITCH)
    assert (m["name"], m["version"], m["developer"], m["engine"], m["os"], m["release"]) == ("Part-Time Witch", "1.0", "Eyed Mushroom", "Unity", "Windows", "2026/04/17")
    assert len(m["genres"]) == 33 and "Magic" in m["genres"] and "Win" not in m["genres"] and "Unity" not in m["genres"]      # платформа и движок вынесены из тегов
    assert m["russian"] == "yes" and m["language"] == "Яп.+Кит.+Англ.+Рус.и др." and m["censor"] == "Отсутствует"
    assert m["size"] == "746.8 MB" and 780_000_000 < m["size_bytes"] < 790_000_000 and m["seeds"] == 176 and m["registered"] == "6 месяцев"
    assert m["torrent"] == "https://pornolab.net/forum/dl.php?t=3282477" and m["needs_login"] and m["thread"] == WITCH
    assert m["cover"].startswith("https://i127.fastpic.org/big/2026/0511/") and m["desc"].startswith("Ты — юная девушка")
    assert m["links"][0]["url"] == m["torrent"] and "нужен вход" in m["links"][0]["label"] and "OS: Windows 10" in m["requirements"]


def test_pornolab_shinobi_and_suzuka_differ_in_language_and_censor():
    s = G.parse_pornolab(fx("pornolab_shinobi.html"), SHINOBI)
    assert (s["name"], s["name_orig"], s["version"], s["russian"], s["size"], s["censor"]) == ("Fallen Shinobi", "忍堕とし", "1.2", "yes", "10.81 GB", "Есть") and s["language"] == "Русский"
    z = G.parse_pornolab(fx("pornolab_suzuka.html"), SUZUKA)
    assert (z["name"], z["version"], z["russian"], z["size"]) == ("Suzuka's Troubles", "v1.1.3", "no", "4.77 GB") and "Частично" in z["censor"] and z["seeds"] == 75
    assert z["language"] == "Японский, Английский" and z["thread"] == SUZUKA


# ---------- Byrutor ----------
def test_byrutor_separates_torrent_version_from_latest_and_reads_language():
    b = G.parse_byrutor(fx("byrutor_aniwars.html"), BYRUT)
    assert (b["name"], b["version"], b["latest"], b["developer"], b["status"], b["release"]) == ("ANIWARS: Call of the Void", "Build 20865732", "Build 24878251", "Breaker Interactive", "Ранний доступ", "17 нояб. 2025")
    assert b["genres"][:3] == ["Тактическая RPG", "Пошаговая тактика", "RPG"] and "Рогалик" in b["genres"] and len(b["genres"]) == len(set(b["genres"]))
    assert b["russian"] == "sub" and b["languages"] == {"story": "", "interface": "Английский", "voice": "Отсутствует", "subtitles": "На русском языке"}
    assert b["size"] == "310 МБ" and b["size_bytes"] == 310 * 1024 ** 2 and b["release_type"] == "Пиратка (Таблетка: Не требуется)"
    assert b["torrent"].endswith("do=download&id=175634") and b["magnet"].endswith("&magnet=1") and not b["needs_login"]
    assert b["alt"] == [{"label": "Файловое хранилище", "version": "Build 24878251", "size": "300 МБ"}] and b["steam_reviews"] == "Очень положительные" and b["updated"] == "24 августа 2026, 17:43"
    assert b["cover"].endswith("aniwars-call-of-the-void.webp") and b["thread"] == BYRUT and b["desc"].startswith("ANIWARS: Call of the Void")


@pytest.mark.parametrize("kw,want", [
    (dict(interface="Английский", subtitles="На русском языке"), "sub"), (dict(interface="Русский"), "yes"), (dict(story="Яп.+Рус."), "yes"), (dict(codes="jap+eng+rus"), "yes"),
    (dict(interface="Английский", voice="Русская"), "voice"), (dict(interface="Английский"), "no"), (dict(), "?"),
])
def test_russian_detection(kw, want): assert G.russian_of(**kw) == want


def test_size_parsing():
    assert G.size_bytes("746.8 MB") == int(746.8 * 1024 ** 2) and G.size_bytes("4,77 ГБ") == int(4.77 * 1024 ** 3) and G.size_bytes("мало") == 0 and G.size_bytes("") == 0


# ---------- карточка: несколько сборок ----------
DRIVER = r'''
import json, sys
sys.path.insert(0, ".")
import app
FIX = json.load(open("fix.json", encoding="utf-8")); P = app.engine_games
app.fetch_cover = lambda *a, **k: ""
app.fetch_html = lambda url, job=None: FIX["pages"].get(url, "")
app.ext_online = lambda: True; app.time.sleep = lambda s: None
def view(name):
    r = app.sql("select * from items where kind='game' and title=?", (name,))
    return (r[0]["id"], app.game_view(r[0]), app.ginfo(r[0]), r[0]) if r else None
out = {}
f95 = {"name": "Suzuka's Troubles", "version": "v1.1.4", "genres": ["3D", "Sandbox"], "developer": "Utatane Club", "language": "English", "links": [], "support": [], "thread": FIX["f95"], "site": "f95"}
app.apply_meta(f95, FIX["f95"])
app.apply_meta(P.parse_pornolab(FIX["pages"][FIX["suz"]], FIX["suz"]), FIX["suz"])
rid, v, info, row = view("Suzuka's Troubles")
out["cards"] = len(app.sql("select 1 from items where kind='game'"))
out["sources"] = [(s["site"], s["version"], s["size"], s["russian"], s["primary"]) for s in v["sources"]]
out["genres_head"] = v["genres"][:3]; out["russian"] = v["russian"]; out["thread"] = v["thread"]; out["src"] = row["src"]
# установленная версия старее источников: обновление есть, и по сборке pornolab тоже
info["inst"] = {"version": "v1.1.2", "versions": 1}; app.ginfo_save(rid, info)
app.apply_meta(P.parse_pornolab(FIX["pages"][FIX["suz"]], FIX["suz"]), FIX["suz"]); out["update"] = view("Suzuka's Troubles")[2].get("update")   # флаг в карточке; на экране он виден у скачанной игры
# только pornolab: главной становится она, f95 потом её не вытесняет «наоборот», а повторное чтение не плодит сборки
app.apply_meta(P.parse_byrutor(FIX["pages"][FIX["byr"]], FIX["byr"]), FIX["byr"]); app.apply_meta(P.parse_byrutor(FIX["pages"][FIX["byr"]], FIX["byr"]), FIX["byr"])
_, vb, ib, rb = view("ANIWARS: Call of the Void")
out["byr"] = {"n": len(vb["sources"]), "latest": vb["sources"][0]["latest"], "russian": vb["russian"], "primary": vb["sources"][0]["primary"], "thread": vb["thread"], "update": vb["update"]}
# проверка версий читает каждую сборку своим разборщиком
FIX["pages"][FIX["suz"]] = FIX["pages"][FIX["suz"]].replace("v1.1.3", "v1.1.9")
job = {"ids": [rid], "cancel": False, "title": "", "pct": 0}; app.game_check(job)
rid, v, info, row = view("Suzuka's Troubles"); out["check"] = job["final"]
out["after_check"] = {s["site"]: s["version"] for s in v["sources"]}
out["classify"] = [app.classify(u)["kind"] + "|" + str(app.classify(u).get("key")) for u in (FIX["suz"] + "&start=20", FIX["byr"], "https://pornolab.net/forum/index.php")]
print("RESULT" + json.dumps(out, ensure_ascii=False))
'''


def test_one_card_keeps_builds_from_each_site_separate():
    tmp = Path(tempfile.mkdtemp(prefix="mh-gs-"))
    try:
        skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
        for e in ROOT.iterdir():
            if e.name in skip or e.suffix == ".zip": continue
            shutil.copytree(e, tmp / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, tmp / e.name)
        (tmp / "settings.json").write_text(json.dumps({"folder": str(tmp / "dl"), "games_root": ""}), "utf-8")
        f95 = "https://f95zone.to/threads/suzukas-troubles.12345/"
        (tmp / "fix.json").write_text(json.dumps({"f95": f95, "suz": SUZUKA, "byr": BYRUT, "pages": {SUZUKA: fx("pornolab_suzuka.html"), BYRUT: fx("byrutor_aniwars.html")}}, ensure_ascii=False), "utf-8")
        (tmp / "driver.py").write_text(DRIVER, "utf-8")
        p = subprocess.run([sys.executable, "driver.py"], cwd=tmp, capture_output=True, text=True, timeout=120, env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1"))
        line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None); assert line, p.stdout[-800:] + p.stderr[-2000:]
        r = json.loads(line[6:])
        assert r["cards"] == 1 and r["sources"] == [["f95", "v1.1.4", "", "no", True], ["pornolab", "v1.1.3", "4.77 GB", "no", False]], r      # одна карточка, две сборки, главная F95zone
        assert r["genres_head"] == ["3D", "Sandbox", "jRPG"], r          # теги главной сборки, затем новые из остальных
        assert r["thread"] == f95 and r["src"] == f95 and r["russian"] == "no" and r["update"] is True, r
        assert r["byr"] == {"n": 1, "latest": "Build 24878251", "russian": "sub", "primary": True, "thread": BYRUT, "update": False}, r        # повторное чтение не плодит сборки
        assert r["check"].startswith("готово: проверено 1, изменилась версия у 1") and "Не удалось: 1" in r["check"], r      # страницы f95 в фикстуре нет: это не ломает проверку остальных сборок
        assert r["after_check"] == {"f95": "v1.1.4", "pornolab": "v1.1.9"}, r
        assert r["classify"] == ["game|" + SUZUKA, "game|" + BYRUT, "unknown|https://pornolab.net/forum/index.php"], r
    finally: shutil.rmtree(tmp, ignore_errors=True)


# ---------- установленные игры и сборки ----------
def test_installed_folder_matches_card_from_pornolab_and_sees_newer_build_on_any_site(server):
    from test_game_find import jget, jpost, wait_scan, make_root, _seed, game
    try:
        root = make_root(server, ["new1/Suzuka's Troubles v1.1.2/game/a.rpy"]); server._sql("delete from items where kind='game'")
        z = G.parse_pornolab(fx("pornolab_suzuka.html"), SUZUKA)           # карточка создана со страницы pornolab (v1.1.3), тема F95zone не добавлялась
        i = _seed(server, "Suzuka's Troubles", "suzukastroubles", {"meta": z, "sources": {"pornolab": z}, "auto": True})
        assert jpost(server, "/api/game/rescan", {})["started"]; wait_scan(server)
        g = game(server, "Suzuka's Troubles")["g"]
        assert g["downloaded"] and g["version"].lstrip("v") == "1.1.2" and g["update"] and g["latest"] == "v1.1.3"          # найдена в папке, есть сборка новее
        assert [s["name"] for s in g["sources"]] == ["PornoLab"] and g["sources"][0]["russian"] == "no" and g["genres"]
    finally: jpost(server, "/api/settings", {"games_root": ""})
