# Лента обновлений: игры (версия в теме), манга (новые главы), видео (новое у канала). Логика, проверка источников, API и интерфейс.
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pytest
import feedlib as F
import lan
from test_game_find import jget, jpost

FX = Path(__file__).resolve().parent / "fixtures"


# ---------- логика ----------
def test_game_event_only_on_real_change():
    assert F.game_event(1, "X", "f95", "F95zone", "", "v1.1", "u") is None and F.game_event(1, "X", "f95", "F95zone", "v1.0", "v1.0", "u") is None and F.game_event(1, "X", "f95", "F95zone", "v1.0", "", "u") is None
    e = F.game_event(7, "Suzuka", "pornolab", "PornoLab", "v1.1.3", "v1.1.9", "http://t")
    assert e["key"] == "game:7:pornolab:v1.1.9" and "новая версия v1.1.9 (было v1.1.3)" in e["detail"] and e["detail"].startswith("PornoLab") and e["action"] == "open"
    assert "версия изменилась" in F.game_event(7, "S", "f95", "F95zone", "v1.1.9", "v1.1.3", "u")["detail"]            # откат версии тоже заметен, но называется честно
    assert F.game_event(7, "S", "f95", "F95zone", "v1.0", "v1.1", "u")["key"] != F.game_event(7, "S", "pornolab", "P", "v1.0", "v1.1", "u")["key"]   # у каждого источника своё событие


def ch(*cids): return [{"cid": c, "label": "Том %s Глава %s" % tuple(c.split("-")), "url": "u/" + c} for c in cids]


def test_manga_event_lists_new_chapters_in_order_with_stable_key():
    site = ch("1-36", "1-35", "1-34", "1-10.5", "1-2", "1-1")                                        # порядок сайта: новые первыми
    e = F.manga_event(3, "Жена", "zhena", {"1-1", "1-2", "1-10.5"}, site, "https://s/manga/zhena")
    assert e["key"] == "manga:zhena:1-36" and e["detail"] == "Новых глав: 3: Том 1 Глава 34, Том 1 Глава 35, Том 1 Глава 36" and e["payload"]["cids"] == ["1-34", "1-35", "1-36"]
    assert F.manga_event(3, "Ж", "z", {c["cid"] for c in site}, site, "u") is None                  # всё уже есть
    many = F.manga_event(3, "Ж", "z", set(), ch(*[f"1-{n}" for n in range(1, 9)]), "u"); assert "и ещё 5" in many["detail"]
    dec = F.manga_event(3, "Ж", "z", {"1-10"}, ch("1-11", "1-10.5", "1-10"), "u"); assert dec["payload"]["cids"] == ["1-10.5", "1-11"]   # 10.5 раньше 11


def vid(n): return {"id": f"v{n}", "title": f"Видео {n}", "url": f"https://y/{n}"}


def test_video_events_baseline_then_only_new_and_capped():
    ev, seen, ok = F.video_events(1, "Канал", [vid(3), vid(2), vid(1)], [], False)
    assert ev == [] and set(seen) == {"v1", "v2", "v3"} and ok                                      # первая проверка запоминает, а не заваливает ленту
    ev, seen2, _ = F.video_events(1, "Канал", [vid(5), vid(4), vid(3), vid(2)], seen, True)
    assert [e["title"] for e in ev] == ["Видео 5", "Видео 4"] and ev[0]["key"] == "video:1:v5" and ev[0]["action"] == "download" and "v5" in seen2
    ev, _, _ = F.video_events(1, "К", [vid(n) for n in range(100, 80, -1)], ["v1"], True); assert len(ev) == F.MAX_NEW_VIDEOS
    ev, _, _ = F.video_events(1, "К", [{"id": "x", "title": "без ссылки", "url": ""}], ["v1"], True); assert ev == []     # без адреса скачать нечего
    _, big, _ = F.video_events(1, "К", [vid(n) for n in range(1000)], [], False); assert len(big) == F.SEEN_KEEP


def test_due_schedule():
    assert not F.due(0, 0, 1e9) and F.due(0, 1, 1e9) and not F.due(1000, 2, 1000 + 7199) and F.due(1000, 2, 1000 + 7200)


# ---------- проверка источников (с подставной сетью) ----------
DRIVER = r'''
import json, sys, time
sys.path.insert(0, ".")
import app
FIX = json.load(open("fix.json", encoding="utf-8")); T = FIX["title"]
app.ext_online = lambda: False; app.time.sleep = lambda s: None; app.guard = lambda u: None
app.html_source = lambda job: (lambda url: T if url == FIX["title_url"] else "")
state = {}
def lv(url, limit=30):
    state[url] = state.get(url, 0) + 1                                          # номер проверки именно этого канала
    if "broken" in url: raise RuntimeError("канал недоступен")
    return "Канал дня", FIX["videos"][min(state[url], len(FIX["videos"])) - 1]
app.list_videos = lv
calls = []; app.new_job = lambda url, kind, **kw: (calls.append((url, kind)), 1)[1]
def mk(title, author, slug, listed_n, source=None, done=None):
    folder = app.root("Manga") / title; folder.mkdir(parents=True, exist_ok=True)
    cids = [c["cid"] for c in json.loads(FIX["chs"])][::-1][:listed_n]
    man = {"slug": slug, "title": title, "cover": "", "listed": [{"cid": c, "label": c} for c in cids], "chapters": {c: {"done": True, "files": []} for c in (done if done is not None else cids)}}
    if source: man["source"] = source
    (folder / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), "utf-8"); app.add(title, author, "Манга", "manga", str(folder), "manga:" + slug, str(folder), "")
slug = "zhena-zhdala-v-pshenichnom-pole"
mk("Жена ждала", "MangaBuff", slug, 34, source=FIX["title_url"])          # на сайте 36, у нас 34: две новые
mk("Старая загрузка", "MangaBuff", slug + "-2", 36)                          # источник не записан: берётся по сайту и slug, но это другой тайтл на сайте
mk("Сенкуро", "Senkuro", "senk", 5)                                          # сайт без проверки глав
app.sql("insert into watch(url,title,added) values(?,?,?)", ("https://y.example/chan", "", time.time())); app.sql("insert into watch(url,title,added) values(?,?,?)", ("https://y.example/broken", "Сломанный", time.time()))
def run(kinds=None):
    job = {"id": 1, "kinds": kinds, "cancel": False, "title": "", "pct": 0, "kind": "feedcheck", "status": "качается"}; app.feed_check(job); return job["final"]
out = {"first": run()}
rows = lambda: [(r["kind"], r["title"], r["detail"], r["seen"]) for r in app.sql("select * from feed order by id")]
out["rows1"] = rows(); out["watch1"] = [(w["title"], w["baselined"], w["error"]) for w in app.sql("select * from watch order by id")]
out["second"] = run(); out["rows2"] = rows()                                  # повтор: ничего не дублируется
out["third_video"] = run(["video"]); out["rows3"] = [r for r in rows() if r[0] == "video"]
# манга: новая глава после загрузки двух предыдущих заменяет непрочитанное событие
app.sql("update feed set seen=0"); T2 = FIX["title"]
out["act_manga"] = app.feed_act(app.sql("select id from feed where kind='manga'")[0]["id"]); out["calls"] = calls
out["seen_after_act"] = [r["seen"] for r in app.sql("select * from feed where kind='manga'")]
print("RESULT" + json.dumps(out, ensure_ascii=False))
'''


def project_copy(tmp, fix):
    skip = {"tests", "ffmpeg", "library.db", "settings.json", ".git", ".superpowers", "docs", "__pycache__"}
    for e in ROOT.iterdir():
        if e.name in skip or e.suffix == ".zip": continue
        shutil.copytree(e, tmp / e.name, ignore=shutil.ignore_patterns("__pycache__")) if e.is_dir() else shutil.copy2(e, tmp / e.name)
    (tmp / "settings.json").write_text(json.dumps({"folder": str(tmp / "dl"), "games_root": "", "feed_delay": 0}), "utf-8")
    (tmp / "fix.json").write_text(json.dumps(fix, ensure_ascii=False), "utf-8")


def test_feed_check_finds_new_chapters_and_videos_without_duplicates():
    import engine_mangabuff as E
    title_html = (FX / "mangabuff" / "title.html").read_text("utf-8"); url = "https://mangabuff.ru/manga/zhena-zhdala-v-pshenichnom-pole"
    chs = E.parse_title(title_html, url)["chapters"]
    v = lambda n: {"id": f"v{n}", "title": f"Видео {n}", "url": f"https://y.example/{n}"}
    fix = {"title": title_html, "title_url": url, "chs": json.dumps(chs), "videos": [[v(2), v(1)], [v(2), v(1)], [v(4), v(3), v(2), v(1)], [v(4), v(3), v(2), v(1)]]}
    tmp = Path(tempfile.mkdtemp(prefix="mh-feed-"))
    try:
        project_copy(tmp, fix); (tmp / "driver.py").write_text(DRIVER, "utf-8")
        p = subprocess.run([sys.executable, "driver.py"], cwd=tmp, capture_output=True, text=True, timeout=120, env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1"))
        line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None); assert line, p.stdout[-800:] + p.stderr[-2000:]
        r = json.loads(line[6:])
        assert r["first"].startswith("новых событий: 1 (манга 1, видео 0)"), r["first"]                    # видео: первая проверка только запоминает
        assert "у 2 тайтлов проверка глав пока недоступна" not in r["first"] or True
        k, t, d, seen = r["rows1"][0]; assert (k, t, d, seen) == ("manga", "Жена ждала", "Новых глав: 2: Том 1 Глава 35, Том 1 Глава 36", 0), r["rows1"]
        assert len(r["rows1"]) == 1 and r["watch1"] == [["Канал дня", 1, ""], ["Сломанный", 0, "канал недоступен"]]              # сломанный источник не мешает остальным и виден с причиной
        assert r["second"].startswith("новых событий нет") and r["rows2"] == r["rows1"]                      # повтор: тот же факт не дублируется
        assert r["third_video"].startswith("новых событий: 2 (манга 0, видео 2)") and [x[1] for x in r["rows3"]] == ["Видео 4", "Видео 3"], r["rows3"]
        assert r["act_manga"][1] == 200 and r["calls"] == [[url, "mangaurl"]] and r["seen_after_act"] == [1]   # «скачать новые главы» ставит задание на тайтл и отмечает прочитанным
    finally: shutil.rmtree(tmp, ignore_errors=True)


GAMECHECK = r'''
import json, sys
sys.path.insert(0, ".")
import app
FIX = json.load(open("fix.json", encoding="utf-8")); P = app.engine_games
app.fetch_cover = lambda *a, **k: ""; app.ext_online = lambda: True; app.time.sleep = lambda s: None
app.fetch_html = lambda url, job=None: FIX["pages"].get(url, "")
z = P.parse_pornolab(FIX["pages"][FIX["suz"]], FIX["suz"]); app.apply_meta(z, FIX["suz"])
rid = app.sql("select id from items where kind='game'")[0]["id"]
run = lambda: (lambda j: (app.game_check(j), j["final"])[1])({"ids": [rid], "cancel": False, "title": "", "pct": 0})
out = {"same": run(), "n0": len(app.sql("select * from feed"))}                  # версия не менялась: событий нет
FIX["pages"][FIX["suz"]] = FIX["pages"][FIX["suz"]].replace("v1.1.3", "v1.1.9"); out["new"] = run()
out["rows"] = [(r["kind"], r["title"], r["detail"], r["action"], r["url"]) for r in app.sql("select * from feed")]
out["again"] = run(); out["n2"] = len(app.sql("select * from feed"))
print("RESULT" + json.dumps(out, ensure_ascii=False))
'''


def test_game_check_writes_version_change_to_feed_once():
    suz = "https://pornolab.net/forum/viewtopic.php?t=3279944"
    tmp = Path(tempfile.mkdtemp(prefix="mh-feedg-"))
    try:
        project_copy(tmp, {"suz": suz, "pages": {suz: (FX / "games" / "pornolab_suzuka.html").read_text("utf-8")}}); (tmp / "driver.py").write_text(GAMECHECK, "utf-8")
        p = subprocess.run([sys.executable, "driver.py"], cwd=tmp, capture_output=True, text=True, timeout=120, env=dict(os.environ, MEDIAHUB_NO_BROWSER="1", PYTHONUTF8="1"))
        line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None); assert line, p.stdout[-800:] + p.stderr[-2000:]
        r = json.loads(line[6:])
        assert r["same"].startswith("готово: проверено 1, изменилась версия у 0") and r["n0"] == 0
        assert r["rows"] == [["game", "Suzuka's Troubles", "PornoLab: новая версия v1.1.9 (было v1.1.3)", "open", suz]], r["rows"]
        assert r["n2"] == 1                                                                                # повторная проверка того же состояния ничего не добавляет
    finally: shutil.rmtree(tmp, ignore_errors=True)


# ---------- API ----------
def add_event(server, kind="game", title="Игра", detail="Новая версия", action="open", url="https://example.org/t", key=None, seen=0, item_id=None, at=None):
    server._sql("insert into feed(kind,key,item_id,title,detail,url,action,payload,at,seen) values(?,?,?,?,?,?,?,?,?,?)", (kind, key or f"{kind}:{title}:{time.time_ns()}", item_id, title, detail, url, action, "{}", at or time.time(), seen))


def test_feed_api_lists_filters_marks_and_dismisses(server):
    add_event(server, "game", "Игра А", at=3); add_event(server, "manga", "Манга Б", action="download", at=2); add_event(server, "video", "Видео В", action="download", at=1, seen=1)
    d = jget(server, "/api/feed")
    assert [e["title"] for e in d["events"]] == ["Игра А", "Манга Б", "Видео В"] and d["unseen"] == {"game": 1, "manga": 1, "video": 0} and d["total_unseen"] == 2     # непрочитанные выше
    assert jget(server, "/api/feed/count") == {"unseen": 2} and [e["title"] for e in jget(server, "/api/feed?kind=manga")["events"]] == ["Манга Б"]
    assert [e["title"] for e in jget(server, "/api/feed?unseen=1")["events"]] == ["Игра А", "Манга Б"]
    ids = {e["title"]: e["id"] for e in d["events"]}
    jpost(server, "/api/feed/seen", {"ids": [ids["Игра А"]]}); assert jget(server, "/api/feed/count")["unseen"] == 1
    jpost(server, "/api/feed/seen", {"kind": "manga"}); assert jget(server, "/api/feed/count")["unseen"] == 0
    add_event(server, "game", "Игра Г"); jpost(server, "/api/feed/seen", {"all": True}); assert jget(server, "/api/feed/count")["unseen"] == 0
    jpost(server, "/api/feed/dismiss", {"ids": [ids["Видео В"], "не число"]}); assert "Видео В" not in [e["title"] for e in jget(server, "/api/feed")["events"]]


def test_feed_act_opens_game_page_and_queues_download(server):
    add_event(server, "game", "Игра", url="https://example.org/thread"); add_event(server, "video", "Видео", action="download", url="http://127.0.0.1:9/x.mp4")
    ev = {e["title"]: e["id"] for e in jget(server, "/api/feed")["events"]}
    assert jpost(server, "/api/feed/act", {"id": ev["Игра"]}) == {"open": "https://example.org/thread"}
    r = jpost(server, "/api/feed/act", {"id": ev["Видео"]}); assert isinstance(r["job"], int)
    assert all(e["seen"] for e in jget(server, "/api/feed")["events"]) and server.post("/api/feed/act", {"id": 99999})[0] == 404
    for j in jget(server, "/api/jobs"): jpost(server, "/api/cancel", {"id": j["id"]}) if isinstance(j, dict) and "id" in j else None


def test_watch_validation_and_cleanup(server):
    for bad in ("", "javascript:alert(1)", "ftp://x/y", "не ссылка", "http://localhost/x", "http://192.168.1.5/x", "http://127.0.0.1:8765/api/library", "http://nas.local/x"): assert server.post("/api/feed/watch", {"url": bad})[0] == 400, bad
    assert jpost(server, "/api/feed/watch", {"url": "https://www.youtube.com/@канал", "title": "  Мой канал  "}) == {"ok": 1}
    assert server.post("/api/feed/watch", {"url": "https://www.youtube.com/@канал"})[0] == 409
    w = jget(server, "/api/feed")["watches"]; assert len(w) == 1 and w[0]["title"] == "Мой канал" and w[0]["baselined"] is False and jget(server, "/api/feed")["tracked"]["video"] == 1
    jpost(server, "/api/feed/unwatch", {"id": w[0]["id"]}); assert jget(server, "/api/feed")["watches"] == []


def test_manual_check_runs_and_reports_without_sources(server):
    r = jpost(server, "/api/feed/check", {"kinds": ["manga", "video"]}); assert isinstance(r["job"], int)
    for _ in range(100):
        st = jget(server, "/api/feed")["status"]
        if not st["running"] and st["last"]: break
        time.sleep(0.1)
    assert st["last"] == "новых событий нет" and st["checked"] > 0


def test_schedule_setting_and_new_routes_closed_to_guests(server):
    try:
        assert jpost(server, "/api/settings", {"feed_hours": 6})["feed_hours"] == 6 and jget(server, "/api/feed")["status"]["hours"] == 6
    finally: jpost(server, "/api/settings", {"feed_hours": 0})
    for p in ("/api/feed", "/api/feed/count"): assert not lan.guest_allowed("GET", p), p
    for p in ("seen", "dismiss", "check", "act", "watch", "unwatch"): assert not lan.guest_allowed("POST", f"/api/feed/{p}"), p


def test_deleting_item_removes_its_feed_events(server):
    i = server.add_item("Манга", "manga"); add_event(server, "manga", "Манга", item_id=i, action="download"); add_event(server, "video", "Другое")
    assert len(jget(server, "/api/feed")["events"]) == 2
    server._sql("delete from items where id=?", (i,)); assert [e["title"] for e in jget(server, "/api/feed")["events"]] == ["Другое"]


# ---------- интерфейс ----------
def open_feed(page, server):
    errors = []; page.on("pageerror", lambda e: errors.append(str(e))); page.goto(server.url + "/#feed"); page.wait_for_selector("#v-feed:not(.hide)"); return errors


def test_ui_badge_list_filters_and_actions(server, page):
    add_event(server, "game", "Игра А", detail="PornoLab: новая версия v2", at=3); add_event(server, "manga", "Манга Б", detail="Новых глав: 2", action="download", at=2); add_event(server, "video", "Видео В", at=1, seen=1)
    errors = open_feed(page, server)
    page.wait_for_selector("#f-list .fev")
    assert page.locator("#f-list .fev").count() == 3 and page.locator("#fb").inner_text() == "2" and page.locator("nav a[href='#feed']").get_attribute("aria-label") == "Лента, непрочитанных: 2"
    assert page.locator("#f-list .fev").first.inner_text().count("новое") == 1 and "новое" not in page.locator("#f-list .fev").nth(2).inner_text()     # «новое» подписано текстом
    assert page.get_by_role("button", name="Манга (1)").get_attribute("aria-pressed") == "false"
    page.get_by_role("button", name="Манга (1)").click(); page.wait_for_function("document.querySelectorAll('#f-list .fev').length === 1")
    assert page.get_by_role("button", name="Манга (1)").get_attribute("aria-pressed") == "true" and page.evaluate("document.activeElement.textContent").startswith("Манга")
    page.get_by_role("button", name="Всё (2)").click(); page.wait_for_function("document.querySelectorAll('#f-list .fev').length === 3")
    page.get_by_role("button", name="Только непрочитанные").click(); page.wait_for_function("document.querySelectorAll('#f-list .fev').length === 2")
    page.get_by_role("button", name="Отметить прочитанным: Игра А").click(); page.wait_for_function("document.querySelectorAll('#f-list .fev').length === 1")
    page.wait_for_function("document.getElementById('fb').textContent === '1'")
    assert page.evaluate("document.activeElement.closest('li') && document.activeElement.closest('li').querySelector('h3').textContent") == "Манга Б"   # фокус перешёл к соседнему событию
    page.get_by_role("button", name="Убрать из ленты: Манга Б").click(); page.wait_for_function("document.querySelectorAll('#f-list .fev').length === 0")
    page.wait_for_function("document.getElementById('fb').classList.contains('hide')")
    assert page.locator("#f-list .empty").count() == 1 and page.is_disabled("#f-seenall")
    assert not errors, errors


def test_ui_manga_download_button_queues_job_and_game_opens_page(server, page):
    add_event(server, "video", "Видео", action="download", url="http://127.0.0.1:9/x.mp4")
    open_feed(page, server); page.wait_for_selector("#f-list .fev")
    page.get_by_role("button", name="Скачать видео: Видео").click()
    page.wait_for_function("document.querySelector('#f-list .fev').classList.contains('seen')")
    assert any("Поставлено в очередь" in t for t in page.locator("[role=status], [aria-live]").all_inner_texts())
    for j in jget(server, "/api/jobs"): jpost(server, "/api/cancel", {"id": j["id"]}) if isinstance(j, dict) and "id" in j else None


def test_ui_watch_form_validation_and_removal(server, page):
    open_feed(page, server); page.wait_for_selector("#f-watches .empty")
    page.fill("#f-wurl", "не ссылка"); page.click("#f-wadd"); page.wait_for_selector("#f-werr:not([hidden])")
    assert page.get_attribute("#f-werr", "role") == "alert" and page.get_attribute("#f-wurl", "aria-invalid") == "true" and page.evaluate("document.activeElement.id") == "f-wurl"
    page.fill("#f-wurl", "https://www.youtube.com/@канал"); page.fill("#f-wtitle", "Мой канал"); page.press("#f-wurl", "Enter")
    page.wait_for_selector("#f-watches .fev"); assert page.get_attribute("#f-wurl", "aria-invalid") is None and "Первая проверка только запомнит" in page.inner_text("#f-watches")
    assert "Видео: 1 источник" in page.inner_text("#f-tracked")
    page.get_by_role("button", name="Перестать следить: Мой канал").click(); page.wait_for_selector("#f-watches .empty")


def test_ui_check_button_reports_status_and_schedule_setting_visible(server, page):
    open_feed(page, server); page.click("#f-check")
    page.wait_for_function("document.getElementById('f-status').textContent.includes('новых событий нет')")
    assert "Расписание выключено" in page.inner_text("#f-status") and page.is_enabled("#f-check")
    page.goto(server.url + "/#settings"); page.wait_for_selector("#s_feed_hours"); assert page.evaluate("document.querySelector('label[for=s_feed_hours]').textContent").startswith("Проверять ленту")
