# Скачанная игра находится по карточке из темы: «Hidden Badge» ↔ new7/HiddenBadge_20260828c, ручная привязка, замена версий.
import json, time
from pathlib import Path

THREAD = "https://f95zone.to/threads/hidden-badge.1/"


def jget(server, path): return json.loads(server.get(path)[2])
def jpost(server, path, body): return json.loads(server.post(path, body)[2])


def wait_scan(server):
    time.sleep(0.3)
    for _ in range(100):
        if not jget(server, "/api/game/scanstate")["running"]: return
        time.sleep(0.2)
    raise AssertionError("scan did not finish")


def make_root(server, files):
    root = server.base / f"PG{time.time_ns()}"                                  # своя папка на каждый тест
    for rel in files:
        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    jpost(server, "/api/settings", {"games_root": str(root)}); wait_scan(server)
    return root


def _seed(server, title, key, info):
    server._sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)",
                (title, "dev", "Игры", "game", "", "", "game:" + key, 0, "", THREAD, json.dumps(info)))
    import sqlite3
    con = sqlite3.connect(server.base / "library.db", timeout=10)
    try: return con.execute("select id from items where url=?", ("game:" + key,)).fetchone()[0]
    finally: con.close()


def game(server, title): return next(x for x in jget(server, "/api/library?q=") if x["title"] == title)


def test_build_date_folder_merges_with_thread_card_after_rescan(server):
    try:
        root = make_root(server, ["new7/HiddenBadge_20260828c/game/a.rpy"])
        server._sql("delete from items where kind='game'")                      # карточка из темы появилась раньше, чем игру скачали
        _seed(server, "Hidden Badge", "hiddenbadge", {"meta": {"version": "20260901", "genres": [], "thread": THREAD}, "auto": True})
        assert not game(server, "Hidden Badge")["path"]
        assert jpost(server, "/api/game/rescan", {})["started"]; wait_scan(server)
        x = game(server, "Hidden Badge")
        assert Path(x["path"]).name == "HiddenBadge_20260828c" and json.loads(x["info"])["inst"]["version"] == "20260828c"
        assert json.loads(x["info"])["update"]                                    # в теме 20260901 новее, чем скачанная 20260828c
        assert len([y for y in jget(server, "/api/library?q=") if y["kind"] == "game"]) == 1   # второй «установленной» карточки нет
    finally: jpost(server, "/api/settings", {"games_root": ""})


def test_locate_offers_candidates_and_manual_link_survives_rescan(server):
    try:
        root = make_root(server, ["new1/Совсем Иначе Названная Папка/game/a.rpy", "new1/Hail Dicktator v0.98.1/game/a.rpy"])
        server._sql("delete from items where kind='game'")
        i = _seed(server, "Hidden Badge Remastered", "hiddenbadgeremastered", {"meta": {"version": "1", "genres": [], "thread": THREAD}, "auto": True})
        r = jpost(server, "/api/game/locate", {"id": i}); wait_scan(server)
        assert not r["downloaded"] and not [c for c in r["found"] if c["score"] >= 0.9]   # названия не совпадают: автоматически не свяжется
        target = str(root / "new1" / "Совсем Иначе Названная Папка")
        assert jpost(server, "/api/game/link", {"id": i, "path": str(server.base / "elsewhere")})["error"]   # только внутри каталога игр
        assert jpost(server, "/api/game/link", {"id": i, "path": target}).get("ok"); wait_scan(server)
        x = game(server, "Hidden Badge Remastered"); assert x["path"] == target
        jpost(server, "/api/game/rescan", {}); wait_scan(server)                  # привязка переживает пересканирование
        assert game(server, "Hidden Badge Remastered")["path"] == target
        assert not [y for y in jget(server, "/api/library?q=") if y["title"] == "Совсем Иначе Названная Папка"]   # дубль-карточки нет
    finally: jpost(server, "/api/settings", {"games_root": ""})


def test_plans_and_replace_job_carry_saves_and_trash_old(server):
    try:
        root = make_root(server, ["new5/Hail Dicktator v0.97.1/game/saves/a.save", "new5/Hail Dicktator v0.97.1/game/script.rpy", "new8/Hail Dicktator v0.98.1/game/script.rpy"])
        pl = jget(server, "/api/game/plans")["items"]; assert len(pl) == 1 and pl[0]["can"] and pl[0]["keeper"]["version"] == "v0.98.1"
        assert jpost(server, "/api/game/replace", {"ids": [pl[0]["id"]]})["error"]            # без подтверждения ничего не делаем
        assert (root / "new5/Hail Dicktator v0.97.1").exists()
        r = jpost(server, "/api/game/replace", {"ids": [pl[0]["id"]], "confirm": True}); assert r["count"] == 1
        for _ in range(100):
            if not (root / "new5/Hail Dicktator v0.97.1").exists(): break
            time.sleep(0.2)
        assert (root / "new8/Hail Dicktator v0.98.1/game/saves/a.save").exists()
        assert not (root / "new5/Hail Dicktator v0.97.1").exists() and any((root / "_GameSweep_Trash").rglob("Hail Dicktator v0.97.1"))
    finally: jpost(server, "/api/settings", {"games_root": ""})
