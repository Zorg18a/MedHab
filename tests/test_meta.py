# Мои данные: избранное, статус, оценка 0–10, теги, описание, своя обложка. Для игр, манги, видео одинаково.
import base64, json, struct, urllib.parse, zlib
from conftest import run_axe

GAME = "Игра"


def png(w=8, h=8):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    ck = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ck(b"IDAT", zlib.compress(raw)) + ck(b"IEND", b"")


def lib(server, q=""):
    return json.loads(server.get("/api/library?q=" + urllib.parse.quote(q))[2])


def test_meta_roundtrip_clamps_rating_and_cleans_tags(server):
    i = server.add_item(title=GAME, kind="game")
    st, _, b = server.post("/api/meta/set", {"id": i, "fav": True, "status": "doing", "rating": 15, "tags": " #RPG, rpg ,, Ren'Py ;  harem ", "descr": "моё описание"})
    m = json.loads(b)["meta"]
    assert m["fav"] and m["status"] == "doing" and m["rating"] == 10 and m["tags"] == ["RPG", "Ren'Py", "harem"] and m["descr"] == "моё описание"
    x = next(y for y in lib(server) if y["id"] == i)
    assert x["m"]["fav"] and x["m"]["rating"] == 10
    json.loads(server.post("/api/meta/set", {"id": i, "rating": None})[2]); assert next(y for y in lib(server) if y["id"] == i)["m"]["rating"] is None
    assert json.loads(server.post("/api/meta/set", {"id": i, "rating": "abc"})[2])["error"]
    assert json.loads(server.post("/api/meta/set", {"id": 99999, "fav": True})[2])["error"]


def test_search_finds_by_my_tag_and_description(server):
    i = server.add_item(title="Совсем другое", kind="game"); server.post("/api/meta/set", {"id": i, "tags": "любимое", "descr": "про космос"})
    assert [x["id"] for x in lib(server, "любимое")] == [i] and [x["id"] for x in lib(server, "космос")] == [i]


def test_custom_cover_is_stored_apart_and_can_be_reset(server):
    i = server.add_item(title=GAME, kind="game")
    bad = json.loads(server.post("/api/cover/set", {"id": i, "data": "data:image/png;base64," + base64.b64encode(b"not an image").decode()})[2]); assert bad["error"]
    r = json.loads(server.post("/api/cover/set", {"id": i, "data": "data:image/png;base64," + base64.b64encode(png()).decode()})[2])
    assert r["cover"].startswith(f"/c/{i}?v=")
    st, h, body = server.get(f"/c/{i}"); assert st == 200 and body[:4] == b"\x89PNG"
    assert next(y for y in lib(server) if y["id"] == i)["cover"].startswith("/c/")
    r2 = json.loads(server.post("/api/cover/clear", {"id": i})[2]); assert r2["cover"] == ""
    assert server.get(f"/c/{i}")[0] == 404


def test_game_panel_favorite_rating_status_show_on_card_and_filter(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    card = page.get_by_role("button", name=f"{GAME}: не скачано"); card.wait_for(); card.press("Enter")
    panel = page.locator("#gpanel")
    panel.get_by_role("button", name="В избранное").click()
    panel.get_by_label("Оценка").select_option("8")
    panel.get_by_label("Статус").select_option("done")
    panel.get_by_label("Теги (через запятую)").fill("любимое, adv"); panel.get_by_label("Теги (через запятую)").press("Tab")
    page.keyboard.press("Escape")
    card = page.get_by_role("button", name=f"{GAME}: не скачано, в избранном, оценка 8 из 10, пройдено"); card.wait_for()
    page.get_by_role("button", name="Избранное").click()                      # фильтр-чип появился, потому что есть избранное
    assert page.locator("#ggrid [data-card]").count() == 1
    page.get_by_role("button", name="Все").first.click()
    page.locator("#gq").fill("любимое"); assert page.locator("#ggrid [data-card]").count() == 1                 # поиск по моим тегам
    page.locator("#gso").select_option("rating")


def test_game_panel_meta_block_is_accessible(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    page.get_by_role("button", name=f"{GAME}: не скачано").press("Enter")
    page.locator("#gpanel").get_by_role("heading", name="Мои данные").wait_for()
    assert run_axe(page) == []


def test_library_edit_dialog_has_meta_and_favorites_chip(server, page):
    i = server.add_media("Ролик", kind="video")
    page.goto(server.url + "/#library")
    for _ in range(5):                                                      # кнопка появляется по наведению; ждём, пока страница подключит обработчики
        page.locator("[data-action=edit]").first.click(force=True)
        if page.locator("#editDlg").evaluate("e=>e.open"): break
        page.wait_for_timeout(300)
    dlg = page.locator("#editDlg"); dlg.get_by_role("button", name="В избранное").click()
    dlg.get_by_label("Оценка").select_option("7")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="★ Избранное").wait_for()
    assert next(y for y in lib(server) if y["id"] == i)["m"]["rating"] == 7


def test_deleted_item_leaves_no_personal_data_for_the_next_one(server):
    # номера удалённых записей используются повторно: чужая оценка не должна прилипнуть к новой записи
    i = server.add_item(title=GAME, kind="game"); server.post("/api/meta/set", {"id": i, "fav": True, "rating": 9, "tags": "старое"})
    server._sql("delete from items where id=?", (i,))                                  # удаление мимо API, как делает пересканирование
    j = server.add_item(title="Новая", kind="game"); assert j == i
    m = next(y for y in lib(server) if y["id"] == j)["m"]
    assert not m["fav"] and m["rating"] is None and m["tags"] == []
