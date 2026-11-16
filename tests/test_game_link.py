# Связь «карточка ↔ папка»: маркер .mediahub.json, память связей (таблица links), причины «не найдено».
import json, os, sqlite3, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gamelink as gl, gamesweep as gs
from test_game_find import jget, jpost, wait_scan, make_root, _seed, game, THREAD


def put(base, rel, data=b"x"):
    p = Path(base) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p


def links(server):
    con = sqlite3.connect(server.base / "library.db", timeout=10)
    try: return {r[0]: (r[1], r[2]) for r in con.execute("select path,item_id,method from links")}
    finally: con.close()


def rescan(server): assert jpost(server, "/api/game/rescan", {})["started"]; wait_scan(server)


def threaded_card(server, files, title="Hidden Badge", key="hiddenbadge"):
    root = make_root(server, files)
    server._sql("delete from items where kind='game'")
    i = _seed(server, title, key, {"meta": {"version": "20260901", "genres": [], "thread": THREAD}, "auto": True})
    rescan(server); return root, i


# ---------- сам маркер ----------
def test_marker_roundtrip_and_idempotent(tmp_path):
    d = tmp_path / "G"; put(d, "game/a.rpy")
    card = {"thread": THREAD, "key": "hiddenbadge", "title": "Hidden Badge", "version": "1"}
    assert gl.write_marker(str(d), card, "auto", 1.6e9)
    m = gl.read_marker(str(d)); assert m["thread"] == THREAD and m["key"] == "hiddenbadge" and m["linked"] == "auto"
    assert not gl.write_marker(str(d), card, "auto", 1.6e9)                  # то же самое: файл не переписывается
    assert gl.write_marker(str(d), card, "manual", 1.6e9) and gl.read_marker(str(d))["linked"] == "manual"


def test_marker_does_not_change_game_age_or_dir_time(tmp_path):
    d = tmp_path / "G"; f = put(d, "game/a.rpy"); os.utime(f, (1.6e9, 1.6e9)); os.utime(d, (1.5e9, 1.5e9))
    size0, new0 = gs._tree_stats(str(d))
    assert gl.write_marker(str(d), {"thread": THREAD, "key": "k"}, "auto", new0)
    size1, new1 = gs._tree_stats(str(d))
    assert new1 == new0 == 1.6e9 and size1 > size0                            # самый свежий файл тот же
    assert int(os.stat(d).st_mtime) == 1500000000                            # время папки не тронуто
    d2 = tmp_path / "H"; put(d2, "a"); assert gl.write_marker(str(d2), {"key": "k"}, "auto", 0)   # время файлов неизвестно
    assert os.stat(d2 / gl.MARKER).st_mtime < 1e9                              # маркер не станет «самым свежим»


def test_foreign_broken_or_huge_markers_are_ignored(tmp_path):
    d = tmp_path / "G"; d.mkdir()
    for raw in (b"not json", b'{"app": "Other", "key": "k"}', b'{"app": "MediaHub"}', b"[1]", b'{"app":"MediaHub","key":"' + b"x" * 5000 + b'"}'):
        (d / gl.MARKER).write_bytes(raw); assert gl.read_marker(str(d)) is None
        assert not gl.remove_marker(str(d)) and (d / gl.MARKER).exists()      # чужой файл не удаляем
    assert gl.read_marker(str(tmp_path / "нет")) is None and not gl.write_marker(str(tmp_path / "нет"), {"key": "k"})


def test_write_failure_is_quiet_and_leaves_no_temp(tmp_path):
    d = tmp_path / "G"; put(d, "a"); real = os.replace
    def boom(*a, **k): raise PermissionError("read-only")
    gl.os.replace = boom
    try: assert not gl.write_marker(str(d), {"key": "k"})
    finally: gl.os.replace = real
    assert not any(p.name.startswith(gl.MARKER) for p in d.iterdir())


# ---------- explain ----------
def g(name, tp="folder"): return {"name": name, "path": "/x/" + name, "type": tp}


def test_explain_cases():
    assert "ни одной папки" in gl.explain("Hidden Badge", [])["lines"][0]
    r = gl.explain("Hidden Badge", [g("Hidden Bridge")]); assert r["best"] and "87" in r["lines"][0] and "Для автоматической привязки" in r["lines"][0]
    assert "не похожа" in gl.explain("Hidden Badge", [g("Совсем Другое Название")])["lines"][0]
    assert "алфавитами" in " ".join(gl.explain("Скрытый Значок", [g("Skrytyj Znachok")])["lines"])
    assert "архив" in gl.explain("Hidden Badge", [g("HiddenBadge.zip", "archive")])["lines"][0]
    assert "подходит" in gl.explain("Hidden Badge", [g("HiddenBadge_20260828c")])["lines"][0]


# ---------- через сервер ----------
def test_marker_written_only_for_thread_cards_and_rescues_renamed_folder(server):
    try:
        root, i = threaded_card(server, ["new7/HiddenBadge_20260828c/game/a.rpy", "new7/Plain Game v1/game/a.rpy"])
        d = root / "new7" / "HiddenBadge_20260828c"; m = gl.read_marker(str(d))
        assert m and m["thread"] == THREAD and m["key"] == "hiddenbadge" and m["version"] == "20260828c"
        assert not (root / "new7" / "Plain Game v1" / gl.MARKER).exists()      # карточка без темы маркера не получает
        assert links(server)[os.path.abspath(d)] == (i, "name")
        (root / "new7" / "HiddenBadge_20260828c").rename(root / "new7" / "HB"); rescan(server)
        x = game(server, "Hidden Badge"); assert Path(x["path"]).name == "HB"
        assert len([y for y in jget(server, "/api/library?q=") if y["kind"] == "game" and y["title"] != "Plain Game"]) == 1   # дубля нет
        assert links(server)[os.path.abspath(root / "new7" / "HB")] == (i, "marker")
    finally: jpost(server, "/api/settings", {"games_root": "", "game_marker": True})


def test_marker_setting_off_writes_nothing_but_existing_marker_still_works(server):
    try:
        jpost(server, "/api/settings", {"game_marker": False})
        root, i = threaded_card(server, ["new1/HiddenBadge_1/game/a.rpy"])
        assert not (root / "new1/HiddenBadge_1" / gl.MARKER).exists()
        gl.write_marker(str(root / "new1/HiddenBadge_1"), {"thread": THREAD, "key": "hiddenbadge"}, "auto", 1.6e9)   # поставлен раньше
        (root / "new1/HiddenBadge_1").rename(root / "new1/Zzz"); rescan(server)
        assert Path(game(server, "Hidden Badge")["path"]).name == "Zzz"
    finally: jpost(server, "/api/settings", {"games_root": "", "game_marker": True})


def test_link_memory_survives_when_name_no_longer_matches(server):
    try:
        root, i = threaded_card(server, ["new1/HiddenBadge_1/game/a.rpy"])
        server._sql("update items set url='game:retitled', title='Totally Retitled' where id=?", (i,))   # карточку переименовали в теме
        server._sql("update items set info=? where id=?", (json.dumps({"meta": {"version": "1", "genres": [], "thread": ""}, "auto": True}), i))
        (root / "new1/HiddenBadge_1" / gl.MARKER).unlink()                      # маркера нет: остаётся только запись в БД
        rescan(server)
        assert game(server, "Totally Retitled")["path"] == str(root / "new1/HiddenBadge_1")
        assert len([y for y in jget(server, "/api/library?q=") if y["kind"] == "game"]) == 1
    finally: jpost(server, "/api/settings", {"games_root": "", "game_marker": True})


def test_manual_link_is_recorded_and_unlink_forgets_it(server):
    try:
        root = make_root(server, ["new1/Совсем Иначе Названная Папка/game/a.rpy"]); server._sql("delete from items where kind='game'")
        i = _seed(server, "Hidden Badge Remastered", "hiddenbadgeremastered", {"meta": {"version": "1", "genres": [], "thread": THREAD}, "auto": True})
        t = root / "new1" / "Совсем Иначе Названная Папка"
        assert jpost(server, "/api/game/link", {"id": i, "path": str(t)}).get("ok"); wait_scan(server)
        assert links(server)[os.path.abspath(t)] == (i, "manual") and gl.read_marker(str(t))["linked"] == "manual"
        assert jpost(server, "/api/game/link", {"id": i, "path": ""}).get("ok"); wait_scan(server)
        assert not gl.read_marker(str(t)) and not game(server, "Hidden Badge Remastered")["path"]
    finally: jpost(server, "/api/settings", {"games_root": "", "game_marker": True})


def test_deleting_card_drops_its_links(server):
    try:
        root, i = threaded_card(server, ["new1/HiddenBadge_1/game/a.rpy"])
        assert links(server); server._sql("delete from items where id=?", (i,))
        assert not [p for p, (iid, _) in links(server).items() if iid == i]
    finally: jpost(server, "/api/settings", {"games_root": "", "game_marker": True})


def test_locate_reports_why(server):
    try:
        root = make_root(server, ["new1/Hidden Bridge/game/a.rpy"]); server._sql("delete from items where kind='game'")
        i = _seed(server, "Hidden Badge", "hiddenbadge", {"meta": {"version": "1", "genres": [], "thread": THREAD}, "auto": True})
        r = jpost(server, "/api/game/locate", {"id": i}); wait_scan(server)
        assert r["why"] and "Hidden Bridge" in r["why"][0] and "Это она" in r["why"][0]
        jpost(server, "/api/settings", {"games_root": str(server.base / "нет-диска")})
        assert "диск" in jpost(server, "/api/game/locate", {"id": i})["error"]
    finally: jpost(server, "/api/settings", {"games_root": ""})
