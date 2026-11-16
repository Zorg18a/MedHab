# Доступ с других устройств (lan.py): PIN, сессии, права гостя, защита от подбора, подмены Host и запросов с чужих сайтов.
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pytest
import lan
from conftest import Server, _free_port
from test_game_find import jget, jpost

GOOD, BAD = "kvartira-77", "wrong-pin-1"


# ---------- модуль ----------
@pytest.mark.parametrize("pin,ok", [("kvartira-77", True), ("12345", False), ("111111", False), ("aaaaaaaa", False), ("123456", False), ("", False), ("qwerty", False), ("Тайный-пин", True)])
def test_pin_rules(pin, ok): assert (lan.valid_pin(pin) == "") is ok


def test_pin_is_hashed_salted_and_checked_constant_time():
    s1, h1 = lan.hash_pin(GOOD); s2, h2 = lan.hash_pin(GOOD)
    assert s1 != s2 and h1 != h2 and GOOD not in h1 and len(h1) == 64                  # соль у каждого своя, PIN в хэше не виден
    assert lan.check_pin(GOOD, s1, h1) and not lan.check_pin(BAD, s1, h1) and not lan.check_pin("", s1, h1) and not lan.check_pin(GOOD, "", "")


def test_sessions_expire_and_clear():
    s = lan.Sessions(); t = s.new(); assert s.ok(t) and s.count() == 1 and not s.ok("") and not s.ok("чужой")
    s.d[t] = time.time() - 1; assert not s.ok(t) and s.count() == 0
    t2 = s.new(); assert s.clear() == 1 and not s.ok(t2)


def test_throttle_locks_after_five_failures_per_address_then_releases():
    now = [1000.0]; th = lan.Throttle(clock=lambda: now[0])
    for _ in range(4): th.fail("1.1.1.1")
    assert th.wait("1.1.1.1") == 0
    th.fail("1.1.1.1"); assert 0 < th.wait("1.1.1.1") <= lan.LOCK_SECONDS and th.wait("2.2.2.2") == 0   # другой адрес не страдает
    now[0] += lan.LOCK_SECONDS + 1; assert th.wait("1.1.1.1") == 0
    th.fail("1.1.1.1"); th.ok("1.1.1.1"); assert th.wait("1.1.1.1") == 0


@pytest.mark.parametrize("host,ok", [("192.168.1.5:8765", True), ("10.0.0.2", True), ("127.0.0.1:8765", True), ("pc-anna:8765", True), ("pc-anna.local", True), ("evil.example", False),
                                     ("pc-anna.evil.example", False), ("", False), ("[::1]:8765", False), ("192.168.1.5.evil.example", False)])
def test_host_header_allowed(host, ok): assert lan.host_allowed(host, own_name="PC-Anna") is ok


def test_same_origin_blocks_foreign_sites():
    assert lan.same_origin("", "192.168.1.5:8765") and lan.same_origin("http://192.168.1.5:8765", "192.168.1.5:8765")
    assert not lan.same_origin("https://evil.example", "192.168.1.5:8765") and not lan.same_origin("http://192.168.1.5:9999", "192.168.1.5:8765")


def test_guest_rights_allow_only_watching_reading_listening_and_progress():
    for p in ("/", "/js/app.js", "/api/library", "/api/continue", "/api/play/3", "/m/5", "/p/5", "/api/manga/5", "/mi/5/100/001.png", "/c/5", "/f/5", "/s/5/index.html", "/sub/3/1.vtt"):
        assert lan.guest_allowed("GET", p), p
    for p in ("/api/settings", "/api/jobs", "/api/inbox", "/api/ext", "/api/games", "/api/disk", "/api/preview", "/api/game/plans", "/api/lan", "/api/sites", "/ext/commands", "/../app.py", "/app.py", "/settings.json", "/library.db"):
        assert not lan.guest_allowed("GET", p), p
    for p in ("/api/progress", "/api/play/pos", "/api/play/forget"): assert lan.guest_allowed("POST", p)
    for p in ("/api/add", "/api/delete", "/api/edit", "/api/reveal", "/api/settings", "/api/scan", "/api/game/replace", "/api/item/download", "/api/lan/logout", "/ingest"): assert not lan.guest_allowed("POST", p), p


def test_scrub_removes_disk_paths_and_games_but_keeps_the_rest():
    data = [{"id": 1, "kind": "video", "title": "x", "path": "C:/a", "root": "C:/", "m": {"path": "p", "tags": "t"}}, {"id": 2, "kind": "game", "title": "g", "path": "D:/g"}]
    assert lan.scrub(data, drop_games=True) == [{"id": 1, "kind": "video", "title": "x", "m": {"tags": "t"}}]
    assert [x["id"] for x in lan.scrub(data)] == [1, 2] and "path" not in lan.scrub(data)[1]


def test_item_ids_found_in_routes():
    assert lan.item_id_of("/f/12/a/b.png") == 12 and lan.item_id_of("/api/play/7") == 7 and lan.item_id_of("/mi/4/100/001.png") == 4 and lan.item_id_of("/api/library") is None


def test_login_page_is_accessible_and_escapes_text():
    h = lan.login_page('<b>"x"</b>').decode()
    assert 'lang="ru"' in h and '<label for="pin">' in h and 'role="alert"' in h and "<b>" not in h and "&lt;b&gt;" in h and 'aria-invalid="true"' in h and 'type="password"' in h


def test_local_addresses_are_real_lan_or_vpn_ipv4():
    import ipaddress
    for a in lan.local_addresses(): assert any(ipaddress.ip_address(a) in n for n in lan.LAN_NETS), a
    for bad in ("192.0.2.2", "127.0.0.1", "169.254.1.1", "8.8.8.8"): assert not any(ipaddress.ip_address(bad) in n for n in lan.LAN_NETS), bad


# ---------- сквозные: сервер, который считает всех «чужими» ----------
@pytest.fixture(scope="module")
def remote():
    base = Path(tempfile.mkdtemp(prefix="mh-lan-"))
    skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
    for e in ROOT.iterdir():
        if e.name in skip or e.suffix == ".zip": continue
        shutil.copytree(e, base / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, base / e.name)
    salt, h = lan.hash_pin(GOOD)
    (base / "settings.json").write_text(json.dumps({"folder": str(base / "dl"), "games_root": "", "lan": True, "lan_pin_salt": salt, "lan_pin_hash": h}), "utf-8")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=base, env=dict(os.environ, MEDIAHUB_PORT=str(port), MEDIAHUB_NO_BROWSER="1", MEDIAHUB_TEST_REMOTE="1", PYTHONUNBUFFERED="1"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try: http.client.HTTPConnection("127.0.0.1", port, timeout=1).request("GET", "/login"); break
        except Exception: time.sleep(0.2)
    else:
        proc.kill(); raise RuntimeError("server did not start")
    srv = Server(proc, port, base)
    srv.video = srv.add_item("Фильм для всех", "video"); srv.game = srv.add_item("Секретная игра", "game", {"name": "Секретная игра"})
    yield srv
    proc.kill(); shutil.rmtree(base, ignore_errors=True)


def req(srv, method, path, body=None, headers=None, cookie="", host=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{srv.port}", **(headers or {})}
    if cookie: h["Cookie"] = f"mh_s={cookie}"
    c.request(method, path, body=body, headers=h); r = c.getresponse(); data = r.read(); c.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data


def login(srv, pin=GOOD):
    s, h, b = req(srv, "POST", "/login", f"pin={pin}", {"Content-Type": "application/x-www-form-urlencoded"})
    return s, h, b


def tok(h): return h["set-cookie"].split("mh_s=")[1].split(";")[0]
def post(srv, path, cookie, body="{}", **h): return req(srv, "POST", path, body, {"X-MH": "1", "Content-Type": "application/json", **h}, cookie)


def test_without_login_pages_redirect_and_api_refuses(remote):
    s, h, _ = req(remote, "GET", "/"); assert s == 303 and h["location"] == "/login"
    s, _, b = req(remote, "GET", "/api/library"); assert s == 401 and "PIN" in json.loads(b)["error"]
    assert req(remote, "GET", "/library.db")[0] in (303, 401, 403) and req(remote, "GET", "/settings.json")[0] in (303, 401, 403)
    s, _, b = req(remote, "GET", "/login"); assert s == 200 and b"PIN" in b and "no-store" in req(remote, "GET", "/login")[1]["cache-control"]


def test_wrong_host_header_is_refused_even_with_pin(remote):
    assert req(remote, "GET", "/login", host="evil.example")[0] == 403
    assert req(remote, "POST", "/login", f"pin={GOOD}", {"Content-Type": "application/x-www-form-urlencoded"}, host="rebind.evil.example")[0] == 403


def test_login_from_foreign_site_origin_is_refused(remote):
    s, _, _ = req(remote, "POST", "/login", f"pin={GOOD}", {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"}); assert s == 403


def test_guest_session_cookie_flags_and_what_guest_sees(remote):
    s, h, b = login(remote, BAD); assert s == 401 and "Неверный PIN".encode() in b and "set-cookie" not in h
    s, h, _ = login(remote); assert s == 303 and h["location"] == "/"
    sc = h["set-cookie"]; assert "HttpOnly" in sc and "SameSite=Strict" in sc and "Path=/" in sc
    t = tok(h)
    assert req(remote, "GET", "/", cookie=t)[0] == 200
    s, _, b = req(remote, "GET", "/api/library", cookie=t); items = json.loads(b)
    assert s == 200 and any(x["title"] == "Фильм для всех" for x in items) and not any(x["kind"] == "game" for x in items)         # игры гостю не показываются
    assert all("path" not in x and "root" not in x for x in items) and "Секретная игра" not in b.decode()
    assert req(remote, "GET", f"/f/{remote.game}", cookie=t)[0] == 403 and req(remote, "GET", f"/api/play/{remote.game}", cookie=t)[0] == 403
    assert req(remote, "GET", "/nope-not-a-route", cookie=t)[0] == 403                                                        # всё, чего нет в списке прав, закрыто


def test_guest_cannot_manage_anything(remote):
    t = tok(login(remote)[1])
    for path in ("/api/settings", "/api/jobs", "/api/inbox", "/api/ext", "/api/games", "/api/disk", "/api/lan", "/api/game/plans", "/ext/commands", "/api/preview"):
        assert req(remote, "GET", path, cookie=t)[0] == 403, path
    for path in ("/api/settings", "/api/add", "/api/delete", "/api/edit", "/api/reveal", "/api/scan", "/api/game/replace", "/api/item/download", "/api/lan/logout", "/api/ext/approve", "/api/cancel", "/api/clear"):
        assert post(remote, path, t)[0] == 403, path
    assert req(remote, "POST", "/ingest", "{}", {"X-MH": "1"}, t)[0] == 403
    s, _, b = post(remote, "/api/settings", t, json.dumps({"games_root": "C:/", "lan": False})); assert s == 403
    assert "lan_pin_hash" not in b.decode()


def test_guest_may_save_progress_but_only_from_our_own_page(remote):
    t = tok(login(remote)[1]); body = json.dumps({"id": remote.video, "pos": 12, "dur": 100})
    assert post(remote, "/api/play/pos", t, body)[0] == 200
    assert req(remote, "POST", "/api/play/pos", body, {"Content-Type": "application/json"}, t)[0] == 403                    # без заголовка нашей страницы
    assert post(remote, "/api/play/pos", t, body, Origin="https://evil.example")[0] == 403                               # со стороннего сайта
    assert post(remote, "/api/play/pos", t, body, Origin=f"http://127.0.0.1:{remote.port}")[0] == 200
    assert post(remote, "/api/play/pos", "forged-cookie-value", body)[0] == 401


def test_extension_endpoints_are_closed_to_everyone_remote(remote):
    t = tok(login(remote)[1])
    for path in ("/ext/hello", "/ext/tabs", "/ext/commands", "/ingest"):
        assert req(remote, "POST", path, "{}", {}, t)[0] == 403 and req(remote, "GET", path, cookie=t)[0] in (403, 404)


def test_guest_ui_loads_without_script_errors(remote, browser):
    t = tok(login(remote)[1]); ctx = browser.new_context(); ctx.set_default_timeout(8000)
    ctx.add_cookies([{"name": "mh_s", "value": t, "domain": "127.0.0.1", "path": "/"}]); pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e))); pg.goto(f"http://127.0.0.1:{remote.port}/")
    pg.wait_for_selector("text=Фильм для всех"); assert not errors, errors
    ctx.close()


def test_pin_brute_force_is_locked_out_even_for_the_right_pin(remote):
    for _ in range(lan.MAX_FAILS): assert login(remote, BAD)[0] in (401, 429)
    s, h, b = login(remote)                                                                                                  # теперь и верный PIN не принимается
    assert s == 429 and "set-cookie" not in h and "Подождите".encode() in b


# ---------- настройки на самом компьютере ----------
def test_settings_never_expose_pin_hash_and_network_mode_needs_a_pin(server):
    try:
        assert "lan_pin_hash" not in jget(server, "/api/settings") and jget(server, "/api/settings")["lan_pin_set"] is False
        assert jpost(server, "/api/settings", {"lan": True})["error"].startswith("Сначала задайте PIN")
        assert "не короче" in jpost(server, "/api/settings", {"lan_pin": "123"})["error"] and "известный" in jpost(server, "/api/settings", {"lan_pin": "qwerty"})["error"]
        r = jpost(server, "/api/settings", {"lan_pin": GOOD}); assert r["lan_pin_set"] is True and "lan_pin_hash" not in r and "lan_pin_salt" not in r
        st = jget(server, "/api/lan"); assert st["enabled"] is False and st["bound"] is False and st["pin_set"] is True and st["restart"] is False
        assert jpost(server, "/api/settings", {"lan": True})["lan"] is True
        st = jget(server, "/api/lan"); assert st["enabled"] and not st["bound"] and st["restart"]            # включено, но сервер ещё слушает только этот компьютер: нужен перезапуск
        assert jpost(server, "/api/lan/logout", {})["ok"] == 1
        assert not any(GOOD in json.dumps(v) for v in jget(server, "/api/settings").values())
    finally: jpost(server, "/api/settings", {"lan": False})
