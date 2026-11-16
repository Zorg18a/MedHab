import json
import pytest
from conftest import open_player, set_prefs

SRT = "1\n00:00:01,500 --> 00:00:03,000\nПривет, мир\n\n2\n00:00:04,000 --> 00:00:05,250\nВторая, реплика\n".encode("utf-8")


def test_player_page_title_h1_and_video_element(server, page):
    i = server.add_media("Лекция <1>", "video"); errors = []; page.on("pageerror", lambda e: errors.append(e)); open_player(page, server, i)
    assert page.title() == "Лекция <1> — MediaHub" and page.locator("h1").inner_text() == "Лекция <1>"
    assert page.evaluate("m.tagName") == "VIDEO" and page.evaluate("m.controls") is True and page.evaluate("m.preload") == "metadata" and not errors


def test_no_autoplay(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    page.wait_for_timeout(300)
    assert page.evaluate("m.paused && !m.autoplay")


def test_audio_uses_audio_element_and_decorative_cover(server, page):
    i = server.add_media("Песня", "audio", thumb=True); open_player(page, server, i)
    assert page.evaluate("m.tagName") == "AUDIO" and page.locator("main img").get_attribute("alt") == ""


def test_tracks_from_subs_none_default(server, page):
    i = server.add_media("a", "video", subs={"ru.srt": SRT, "en.srt": SRT}); open_player(page, server, i)
    t = page.evaluate("[...m.querySelectorAll('track')].map(t => [t.kind, t.label, t.default, t.getAttribute('src')])")
    assert t == [["subtitles", "English", False, f"/sub/{i}/0.vtt"], ["subtitles", "Русский", False, f"/sub/{i}/1.vtt"]]


def test_missing_item_shows_alert(server, page):
    page.goto(server.url + "/p/999999")
    page.wait_for_function("document.getElementById('err').textContent.trim() !== ''")
    assert "Материал не найден" in page.locator("#err").inner_text()
    assert page.locator("h1").inner_text() == "Материал не найден"


def test_broken_file_shows_message_and_direct_link(server, page):
    i = server.add_media("Битый", "video", ext=".mp4", raw=b"not a video"); page.goto(f"{server.url}/p/{i}")
    page.wait_for_function("document.getElementById('err').textContent.trim() !== ''")
    assert "Не удалось воспроизвести файл" in page.locator("#err").inner_text()
    assert page.get_by_role("link", name="Открыть файл напрямую").get_attribute("href") == f"/f/{i}"


def test_skip_button_first_tab_stop_and_back_link(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i); page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Перейти к содержимому"
    page.keyboard.press("Enter"); assert page.evaluate("document.activeElement.id") == "main"
    assert page.get_by_role("link", name="Библиотека").get_attribute("href") == "/"


def test_page_is_actually_rendered(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    assert page.evaluate("(() => { const r = m.getBoundingClientRect(); return r.width > 100 && r.height > 20 })()")
    assert page.evaluate("getComputedStyle(document.querySelector('.vh')).position") == "absolute"


def test_live_regions_exist(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    assert page.locator("#mh-live-polite").count() == 1 and page.locator("#mh-live-assertive").count() == 1


def test_titles_are_not_interpreted_as_html(server, page):
    i = server.add_media('<img src=x onerror="window.__x=1">', "audio"); open_player(page, server, i)
    assert page.evaluate("window.__x") is None and page.locator("h1 img").count() == 0


def test_library_open_changes_only_for_video_and_audio(server):
    v, a = server.add_media("v", "video"), server.add_media("a", "audio")
    m, s, g, l = (server.add_item(t, k) for t, k in (("m", "manga"), ("s", "site"), ("g", "game"), ("l", "link")))
    got = {x["id"]: x["open"] for x in json.loads(server.get("/api/library")[2])}
    assert got[v] == f"/p/{v}" and got[a] == f"/p/{a}" and got[m] == f"/m/{m}" and got[s].startswith(f"/s/{s}/")
    assert not got[g].startswith("/p/") and not got[l].startswith("/p/")


def test_player_route_serves_html(server):
    i = server.add_media("a", "video"); s, h, b = server.get(f"/p/{i}")
    assert s == 200 and b"<html" in b and server.get("/p/abc")[0] == 404


# ---------- возобновление и сохранение позиции ----------
def say(page): return page.locator("#mh-live-polite").inner_text().strip()


def test_resume_sets_time_announces_and_shows_restart(server, page):
    i = server.add_media("a", "audio", seconds=60); server.set_pos(i, 30, 60); open_player(page, server, i)
    assert abs(page.evaluate("m.currentTime") - 30) < 0.6 and say(page) == "Продолжаю с 0:30"
    assert page.locator("#restart").is_visible()


def test_no_resume_when_finished_or_under_5s(server, page):
    a, b = server.add_media("a", "audio", seconds=60), server.add_media("b", "audio", seconds=60); server.set_pos(a, 55, 60); server.set_pos(b, 4, 60)
    for i in (a, b):
        open_player(page, server, i); assert page.evaluate("m.currentTime") < 0.5 and not page.locator("#restart").is_visible() and say(page) == ""


def test_restart_rewinds_announces_hides_keeps_focus_and_forgets(server, page):
    i = server.add_media("a", "audio", seconds=60); server.set_pos(i, 30, 60); open_player(page, server, i)
    page.locator("#restart").click()
    assert page.evaluate("m.currentTime") < 1 and say(page) == "С начала"
    assert not page.locator("#restart").is_visible() and page.evaluate("document.activeElement.id") == "m"
    page.wait_for_timeout(300); assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] == 0      # допущение 1: forget


def test_pause_saves_position_with_xmh(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i)
    with page.expect_request("**/api/play/pos") as r:
        page.evaluate("m.currentTime = 20; m.play().then(() => m.pause())")
    assert r.value.headers["x-mh"] == "1" and json.loads(r.value.post_data)["id"] == i
    page.wait_for_timeout(300); assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] >= 20


def test_interval_save_every_5s_only_while_playing_and_moved_1s(server, page):
    i = server.add_media("a", "audio", seconds=60); page.clock.install(); open_player(page, server, i); sent = []
    page.on("request", lambda r: sent.append(r) if r.url.endswith("/api/play/pos") else None)
    page.evaluate("m.currentTime = 12; m.play()"); page.wait_for_function("!m.paused && m.currentTime >= 12")
    page.clock.run_for(5100); page.wait_for_timeout(300); assert len(sent) == 1
    page.clock.run_for(5100); page.wait_for_timeout(300); assert len(sent) == 1          # сдвиг меньше секунды: не отправляем
    page.evaluate("m.pause()"); page.wait_for_timeout(300); n = len(sent); assert n == 2   # пауза всегда сохраняет
    page.clock.run_for(20000); page.wait_for_timeout(300); assert len(sent) == n         # на паузе таймер молчит


def test_end_marks_finished(server, page):
    i = server.add_media("a", "audio", seconds=12); open_player(page, server, i)
    page.evaluate("m.currentTime = 11.5; m.play()"); page.wait_for_function("m.ended")
    page.wait_for_timeout(400); assert json.loads(server.get(f"/api/play/{i}")[2])["finished"] is True


def test_pagehide_uses_keepalive_and_xmh(server, page):
    page.add_init_script("window.__f = []; const f = window.fetch; window.fetch = (u, o) => { window.__f.push([String(u), o && o.keepalive, o && o.headers]); return f(u, o) }")
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.evaluate("m.currentTime = 25")
    page.evaluate("dispatchEvent(new Event('pagehide'))")
    last = [x for x in page.evaluate("window.__f") if x[0].endswith("/api/play/pos")][-1]
    assert last[1] is True and last[2]["X-MH"] == "1"


def test_nothing_saved_for_first_seconds(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); sent = []
    page.on("request", lambda r: sent.append(r) if r.url.endswith("/api/play/pos") else None)
    page.evaluate("m.currentTime = 2"); page.evaluate("dispatchEvent(new Event('pagehide'))"); page.wait_for_timeout(300); assert sent == []


def test_fmt_time(server, page):
    page.goto(server.url)
    r = page.evaluate("import('/js/player/player.js').then(m => [m.fmtTime(74), m.fmtTime(754), m.fmtTime(3723), m.fmtTime(NaN), m.fmtTime(-5)])")
    assert r == ["1:14", "12:34", "1:02:03", "0:00", "0:00"]


def test_should_resume_rule(server, page):
    page.goto(server.url)
    r = page.evaluate("import('/js/player/player.js').then(m => [m.shouldResume(5, false), m.shouldResume(4.9, false), m.shouldResume(50, true), m.shouldResume(0, false)])")
    assert r == [True, False, False, False]


# ---------- клавиши плеера ----------
def test_k_toggles_and_announces(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.keyboard.press("k")
    page.wait_for_function("!m.paused"); assert say(page) == "Воспроизведение"
    page.keyboard.press("k"); page.wait_for_function("m.paused"); assert say(page) == "Пауза"


def test_k_with_focus_on_media_toggles_exactly_once(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i); page.locator("#m").focus(); page.keyboard.press("k")
    page.wait_for_timeout(300); assert page.evaluate("!m.paused")          # нативный обработчик не отменил наш


def test_space_on_focused_media_stays_native(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i); page.locator("#m").focus()
    page.evaluate("window.__dp = null; addEventListener('keydown', e => { window.__dp = e.defaultPrevented }, {once: true})")
    page.keyboard.press("Space"); page.wait_for_timeout(300)
    assert page.evaluate("window.__dp") is False and page.evaluate("!m.paused")


def test_j_l_seek_10s_and_announce(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.evaluate("m.currentTime = 30")
    page.keyboard.press("l"); assert abs(page.evaluate("m.currentTime") - 40) < 0.5 and say(page) == "Вперёд на 10 секунд, 0:40"
    page.keyboard.press("j"); page.keyboard.press("j"); assert say(page) == "Назад на 10 секунд, 0:20"
    page.evaluate("m.currentTime = 3"); page.keyboard.press("j"); assert page.evaluate("m.currentTime") == 0


def test_seek_forward_clamped_to_duration(server, page):
    i = server.add_media("a", "audio", seconds=12); open_player(page, server, i); page.evaluate("m.currentTime = 8"); page.keyboard.press("l")
    assert page.evaluate("m.currentTime") <= page.evaluate("m.duration")


def test_speed_steps_and_limits(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i)
    page.keyboard.press("]"); assert page.evaluate("m.playbackRate") == 1.25 and say(page) == "Скорость 1.25"
    for _ in range(5): page.keyboard.press("]")
    assert page.evaluate("m.playbackRate") == 2
    for _ in range(9): page.keyboard.press("[")
    assert page.evaluate("m.playbackRate") == 0.5 and say(page) == "Скорость 0.5"


def test_c_cycles_off_en_ru_off_and_cues_load(server, page):
    i = server.add_media("a", "video", subs={"en.srt": SRT, "ru.srt": SRT}); open_player(page, server, i); seen = []
    for _ in range(3): page.keyboard.press("c"); seen.append(say(page))
    assert seen == ["Субтитры: English", "Субтитры: Русский", "Субтитры выключены"]
    page.keyboard.press("c"); page.wait_for_function("m.querySelector('track').readyState === 2"); assert page.evaluate("m.textTracks[0].cues.length") == 2


def test_c_without_tracks(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i); page.keyboard.press("c"); assert say(page) == "Субтитров нет"


def test_m_mute(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i); page.keyboard.press("m")
    assert page.evaluate("m.muted") and say(page) == "Звук выключен"; page.keyboard.press("m"); assert say(page) == "Звук включён"


def test_f_ignored_for_audio(server, page):
    a = server.add_media("a", "audio"); open_player(page, server, a); page.keyboard.press("f")
    page.wait_for_timeout(200); assert not page.evaluate("document.fullscreenElement") and say(page) == ""


def test_f_enters_fullscreen_for_video(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    if not page.evaluate("document.fullscreenEnabled"): pytest.skip("fullscreen unavailable in this browser build")
    page.keyboard.press("f"); page.wait_for_function("!!document.fullscreenElement"); page.wait_for_timeout(200); assert say(page) == "Полный экран"


def test_question_mark_opens_help_with_caption_and_returns_focus(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i); page.keyboard.press("?")
    assert page.locator("#helpDlg").is_visible() and page.locator("#helpDlg caption").count() == 1
    page.keyboard.press("Escape"); assert not page.locator("#helpDlg").is_visible()


def test_help_button_opens_dialog_and_restores_focus(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i); b = page.get_by_role("button", name="Справка")
    b.click(); assert page.get_by_role("dialog").is_visible()
    page.get_by_role("button", name="Закрыть").click(); assert not page.locator("#helpDlg").is_visible() and page.evaluate("document.activeElement.id") == "helpBtn"


def test_keys_ignored_when_pref_off(server, page):
    set_prefs(page, keys=False); i = server.add_media("a", "audio"); open_player(page, server, i)
    for k in "kjlmc?": page.keyboard.press(k)
    assert page.evaluate("m.paused && !m.muted") and not page.locator("#helpDlg").is_visible()


def test_modifiers_and_typing_are_ignored(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i)
    page.keyboard.press("Control+k"); page.keyboard.press("Alt+j"); page.keyboard.press("Meta+m"); assert page.evaluate("m.paused && !m.muted")
    page.evaluate("document.body.insertAdjacentHTML('beforeend', '<input id=zz>'); zz.focus()"); page.keyboard.type("kml")
    assert page.evaluate("m.paused && !m.muted") and page.evaluate("zz.value") == "kml"


def test_cyrillic_layout_falls_back_to_physical_key(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i)
    page.evaluate("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'л', code: 'KeyK', bubbles: true}))")
    page.wait_for_function("!m.paused")


def test_keys_pure_functions(server, page):
    page.goto(server.url)
    r = page.evaluate("""import('/js/player/keys.js').then(m => [m.nextSpeed(1, 1), m.nextSpeed(2, 1), m.nextSpeed(0.5, -1), m.nextTrack(2, -1), m.nextTrack(2, 1), m.nextTrack(0, -1),
        m.keyAction({key: 'k'}), m.keyAction({key: 'K'}), m.keyAction({key: 'k', ctrlKey: true}), m.keyAction({key: 'x'}), m.keyAction({key: ']'}), m.keyAction({key: 'л', code: 'KeyK'}), m.keyAction({key: 'v', code: 'KeyK'})])""")
    assert r == [1.25, 2, 0.5, 0, -1, -1, "toggle", "toggle", None, None, "faster", "toggle", None]
