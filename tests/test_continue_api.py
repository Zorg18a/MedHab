import json


def cont(server): return json.loads(server.get("/api/continue")[2])


def test_video_item_fields_and_label(server):
    i = server.add_media("Лекция", "video"); server.set_pos(i, 2880, 3600)
    [d] = cont(server)
    assert d["id"] == i and d["kind"] == "video" and d["open"] == f"/p/{i}" and d["pct"] == 80
    assert d["label"] == "осталось 12 мин" and d["title"] == "Лекция" and d["pos"] == 2880 and d["dur"] == 3600 and d["cover"] == ""


def test_rest_label_variants(server):
    a, b, c, e, f = (server.add_media(n, "audio") for n in "abcef")
    server.set_pos(a, 100, 3900, updated=5)      # осталось 3800 с = 1 ч 3 мин 20 с -> округление вверх
    server.set_pos(b, 100, 10900, updated=4)     # ровно 3 часа
    server.set_pos(c, 100, 130, updated=3)       # 30 с
    server.set_pos(e, 754, 0, updated=2)         # длительность неизвестна
    server.set_pos(f, 100, 3700, updated=1)      # ровно час
    labels = {d["id"]: d["label"] for d in cont(server)}
    assert labels == {a: "осталось 1 ч 4 мин", b: "осталось 3 ч", c: "осталось меньше минуты", e: "остановлено на 12:34", f: "осталось 1 ч"}


def test_finished_and_under_5s_excluded(server):
    a, b = server.add_media("a", "audio"), server.add_media("b", "audio"); server.set_pos(a, 95, 100); server.set_pos(b, 4, 100)
    assert cont(server) == []


def test_order_fresh_first_and_limit_6(server):
    ids = [server.add_media(f"m{k}", "audio") for k in range(8)]
    for k, i in enumerate(ids): server.set_pos(i, 20, 1000, updated=1000 + k)
    assert [d["id"] for d in cont(server)] == ids[::-1][:6]


def test_manga_label_pct_open_and_hidden_without_manifest(server):
    m = server.add_manga("Манга", chapters=4, pages=20, progress=(2, 13), updated=50)
    bad = server.add_manga("Без манифеста", manifest=False, progress=(0, 1), updated=60)
    got = cont(server); d = [x for x in got if x["id"] == m][0]
    assert d["open"] == f"/m/{m}" and d["label"] == "глава 3, стр. 14" and d["pct"] == 75 and d["kind"] == "manga"
    assert bad not in [x["id"] for x in got]


def test_manga_pct_counts_among_downloaded_only(server):
    m = server.add_manga("Манга", chapters=4, pages=2, missing=(0,), progress=(2, 0), updated=5)
    [d] = cont(server)
    assert d["id"] == m and d["pct"] == 67       # 2-я из 3 скачанных


def test_progress_without_updated_is_oldest(server):
    v = server.add_media("v", "audio"); server.set_pos(v, 30, 100, updated=5); m = server.add_manga("М", progress=(0, 0), updated=None)
    assert [d["id"] for d in cont(server)][-1] == m


def test_progress_post_sets_updated_so_manga_rises(server):
    v = server.add_media("v", "audio"); server.set_pos(v, 30, 100); m = server.add_manga("М", chapters=2)
    cid = json.loads(server.get(f"/api/manga/{m}")[2])["chapters"][0]["id"]; server.post("/api/progress", {"id": m, "cid": cid, "page": 1})
    assert cont(server)[0]["id"] == m


def test_forget_manga_removes_progress_row(server):
    m = server.add_manga("М", progress=(0, 3), updated=9); server.post("/api/play/forget", {"id": m})
    assert m not in [d["id"] for d in cont(server)] and json.loads(server.get(f"/api/manga/{m}")[2])["progress"] is None


def test_continue_keeps_host_check(server): assert server.get("/api/continue", {"Host": "evil.example"})[0] == 403
