import json
import pytest
from conftest import set_prefs


def open_reader(page, server, i):
    page.goto(f"{server.url}/m/{i}"); page.wait_for_selector("#v img")


def say(page): return page.locator("#mh-live-polite").inner_text().strip()


# ---- характеризационные тесты: описывают поведение ДО переноса и обязаны пройти и после ----
def test_loads_chapter_list_and_images(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2); open_reader(page, server, i)
    assert page.locator("#c option").count() == 3 and page.locator("#v img").count() == 2 and page.title() == "Манга"


def test_resumes_at_saved_chapter_and_page(server, page):
    i = server.add_manga("Манга", chapters=3, pages=5, progress=(1, 3)); open_reader(page, server, i)
    assert page.evaluate("+document.getElementById('c').value") == 1
    page.wait_for_timeout(300)
    top = page.evaluate("document.querySelectorAll('#v img')[3].getBoundingClientRect().top"); hdr = page.evaluate("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hdr')) || 0")
    assert -2 <= top - hdr <= 3          # страница лежит сразу под шапкой, а не под ней


def test_scroll_saves_progress_with_xmh(server, page):
    i = server.add_manga("Манга", chapters=2, pages=3); open_reader(page, server, i)
    with page.expect_request("**/api/progress") as r: page.mouse.wheel(0, 900)
    b = json.loads(r.value.post_data); assert b["id"] == i and r.value.headers["x-mh"] == "1" and "cid" in b and "page" in b


def test_not_downloaded_chapter_message(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2, missing=(1,)); open_reader(page, server, i)
    page.select_option("#c", "1"); assert "ещё не скачана" in page.locator("#v").inner_text()


def test_unknown_title_message(server, page):
    page.goto(server.url + "/m/999999"); page.wait_for_function("document.getElementById('t').textContent !== 'Читалка'")
    assert page.locator("#t").inner_text() == "Тайтл не найден"


# ---- новое поведение этой задачи ----
def test_next_chapter_button_works_without_inline_handlers(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2); open_reader(page, server, i)
    assert page.evaluate("document.querySelectorAll('[onclick]').length") == 0
    page.locator("#v").get_by_role("button", name="Следующая глава").click(); assert page.evaluate("+document.getElementById('c').value") == 1


def test_next_button_in_not_downloaded_chapter_also_works(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2, missing=(1,)); open_reader(page, server, i)
    page.select_option("#c", "1"); assert page.evaluate("document.querySelectorAll('[onclick]').length") == 0
    page.locator("#v").get_by_role("button", name="Следующая глава").click(); assert page.evaluate("+document.getElementById('c').value") == 2


def test_script_is_module_and_no_errors(server, page):
    errors = []; page.on("pageerror", lambda e: errors.append(e)); i = server.add_manga("Манга"); open_reader(page, server, i)
    assert page.locator("script[type=module][src='/js/reader/reader.js']").count() == 1 and page.locator("script:not([src]):not([type])").count() == 1 and not errors


def test_live_regions_and_skip_button_exist(server, page):
    i = server.add_manga("Манга"); open_reader(page, server, i)
    assert page.locator("#mh-live-polite").count() == 1 and page.locator("#mh-live-assertive").count() == 1
    page.keyboard.press("Tab"); assert page.evaluate("document.activeElement.textContent.trim()") == "Перейти к содержимому"
    page.keyboard.press("Enter"); assert page.evaluate("document.activeElement.id") == "main"


# ---------- режимы вписывания и масштаб ----------
def js_m(page, expr): return page.evaluate(f"import('/js/reader/modes.js').then(m => {expr})")


@pytest.mark.parametrize("z,want", [(10, 50), (49, 50), (55, 60), (104, 100), (105, 110), (999, 200), (None, 100), ("abc", 100)])
def test_clamp_zoom(server, page, z, want):
    page.goto(server.url); assert js_m(page, f"m.clampZoom({json.dumps(z)})") == want


def test_image_style_values(server, page):
    page.goto(server.url)
    assert js_m(page, "m.imageStyle('width', 120)")["--pg-w"] == "120%"
    assert js_m(page, "m.imageStyle('width', 120)")["--pg-zoom"] == "1"
    assert "1.2" in js_m(page, "m.imageStyle('height', 120)")["--pg-h"]
    o = js_m(page, "m.imageStyle('orig', 120)"); assert o["--pg-w"] == "auto" and o["--pg-h"] == "auto" and o["--pg-zoom"] == "1.2"
    assert js_m(page, "m.FITS") == ["width", "height", "orig"]


def test_prefs_default_roundtrip_corrupt_and_blocked(server, page):
    page.goto(server.url); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 100}
    page.evaluate("localStorage.setItem('mh.reader', '{broken')"); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 100}
    page.evaluate("localStorage.setItem('mh.reader', 'null')"); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 100}
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'zzz', zoom: 1000}))"); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 200}
    p = page.context.new_page(); p.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})"); errors = []; p.on("pageerror", lambda e: errors.append(e))
    i = server.add_manga("М"); p.goto(f"{server.url}/m/{i}"); p.wait_for_selector("#v img"); assert not errors
    p.get_by_role("button", name="Увеличить масштаб").click(); assert not errors


def widths(page): return page.evaluate("[...document.querySelectorAll('#v img')].map(i => Math.round(i.getBoundingClientRect().width))")


def test_fit_width_orig_and_zoom_change_rendered_sizes(server, page):
    i = server.add_manga("М", pages=2); page.set_viewport_size({"width": 1200, "height": 800}); open_reader(page, server, i)
    assert widths(page)[0] == 900
    page.get_by_role("radio", name="Исходный размер").click(); assert widths(page)[0] == 800
    for _ in range(2): page.get_by_role("button", name="Увеличить масштаб").click()
    assert widths(page)[0] == 960
    page.get_by_role("radio", name="По высоте").click(); h = page.evaluate("document.querySelector('#v img').getBoundingClientRect().height"); assert 600 < h < 800 * 1.3


def test_zoom_live_region_value_and_limits(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); b = page.get_by_role("button", name="Увеличить масштаб")
    for _ in range(12): b.click()
    txt = lambda: " ".join(page.locator("#zv").inner_text().split())
    assert txt() == "Масштаб 200 %" and page.locator("#zv").get_attribute("aria-live") == "polite"
    d = page.get_by_role("button", name="Уменьшить масштаб")
    for _ in range(20): d.click()
    assert txt() == "Масштаб 50 %"


def test_radiogroup_semantics_and_arrow_keys(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); g = page.get_by_role("radiogroup", name="Вписывание")
    assert g.get_by_role("radio").count() == 3 and g.get_by_role("radio", name="По ширине").get_attribute("aria-checked") == "true"
    g.get_by_role("radio", name="По ширине").focus(); page.keyboard.press("ArrowRight")
    assert g.get_by_role("radio", name="По высоте").get_attribute("aria-checked") == "true" and g.get_by_role("radio", name="По ширине").get_attribute("aria-checked") == "false"


def test_choice_persists_in_mh_reader(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); page.get_by_role("radio", name="Исходный размер").click(); page.get_by_role("button", name="Увеличить масштаб").click()
    assert page.evaluate("JSON.parse(localStorage.getItem('mh.reader'))") == {"fit": "orig", "zoom": 110}
    page.reload(); page.wait_for_selector("#v img"); assert page.get_by_role("radio", name="Исходный размер").get_attribute("aria-checked") == "true"
    assert " ".join(page.locator("#zv").inner_text().split()) == "Масштаб 110 %"


def test_mode_change_keeps_current_page_in_view(server, page):
    i = server.add_manga("М", pages=6); open_reader(page, server, i); page.locator("#v img").nth(3).scroll_into_view_if_needed(); page.wait_for_timeout(200)
    k = page.evaluate("(() => { const im = [...document.querySelectorAll('#v img')]; const k = im.findIndex(x => x.getBoundingClientRect().bottom > 70); return k < 0 ? 0 : k })()")
    page.get_by_role("radio", name="По высоте").click(); page.wait_for_timeout(300)
    top = page.evaluate(f"document.querySelectorAll('#v img')[{k}].getBoundingClientRect().top"); hdr = page.evaluate("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hdr')) || 0"); assert -2 <= top - hdr <= 3


def test_document_does_not_scroll_horizontally_at_320_and_200_percent(server, page):
    i = server.add_manga("М"); page.set_viewport_size({"width": 320, "height": 640}); open_reader(page, server, i)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'width', zoom: 200}))"); page.reload(); page.wait_for_selector("#v img")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'orig', zoom: 100}))"); page.reload(); page.wait_for_selector("#v img")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_header_controls_are_rendered_and_named(server, page):
    i = server.add_manga("М"); open_reader(page, server, i)
    for name in ("Уменьшить масштаб", "Увеличить масштаб"):
        b = page.get_by_role("button", name=name); assert b.is_visible() and b.bounding_box()["width"] > 20
    assert page.evaluate("getComputedStyle(document.querySelector('#zv .vh')).position") == "absolute"


def test_header_does_not_cover_the_screen_on_narrow_viewport(server, page):
    i = server.add_manga("М"); page.set_viewport_size({"width": 320, "height": 640}); open_reader(page, server, i)
    assert page.evaluate("getComputedStyle(document.querySelector('header')).position") == "static"
    page.set_viewport_size({"width": 1000, "height": 640}); assert page.evaluate("getComputedStyle(document.querySelector('header')).position") == "sticky"


def test_height_mode_ignores_header_when_it_is_not_sticky(server, page):
    i = server.add_manga("М"); page.set_viewport_size({"width": 320, "height": 640}); page.add_init_script("localStorage.setItem('mh.reader', JSON.stringify({fit: 'height', zoom: 100}))")
    open_reader(page, server, i); page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.style.getPropertyValue('--hdr')") == "0px"


# ---------- клавиши читалки ----------
def cur_chapter(page): return page.evaluate("+document.getElementById('c').value")


def wait_say(page, text, timeout=3000):
    page.wait_for_function("t => document.getElementById('mh-live-polite').textContent.replace(/\\s+/g, ' ').trim() === t", arg=text, timeout=timeout)


def test_chapter_keys_announce_and_focus_h2(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    page.keyboard.press("n"); wait_say(page, "Глава 2 из 3")
    assert page.evaluate("document.activeElement.id") == "ch" and page.locator("#ch").evaluate("e => e.tagName") == "H2" and page.locator("#ch").inner_text() == "Глава 2"
    page.keyboard.press("ArrowRight"); wait_say(page, "Глава 3 из 3")
    page.keyboard.press("p"); wait_say(page, "Глава 2 из 3"); page.keyboard.press("ArrowLeft"); wait_say(page, "Глава 1 из 3")


def test_heading_shows_chapter_without_stealing_focus_on_first_load(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    assert page.locator("#ch").inner_text() == "Глава 1" and page.evaluate("document.activeElement.id") != "ch" and say(page) == ""


def test_edges_do_not_wrap_and_say_so(server, page):
    i = server.add_manga("М", chapters=2); open_reader(page, server, i)
    page.keyboard.press("p"); wait_say(page, "Это первая глава"); assert cur_chapter(page) == 0
    page.keyboard.press("n"); wait_say(page, "Глава 2 из 2"); page.keyboard.press("n"); wait_say(page, "Это последняя глава"); assert cur_chapter(page) == 1


def test_not_downloaded_chapter_is_announced(server, page):
    i = server.add_manga("М", chapters=3, missing=(1,)); open_reader(page, server, i); page.keyboard.press("n"); wait_say(page, "Глава 2 из 3, не скачана")


def test_select_and_header_buttons_announce_but_keep_focus(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    page.locator("#c").focus(); page.select_option("#c", "1"); wait_say(page, "Глава 2 из 3"); assert page.evaluate("document.activeElement.id") == "c"
    page.locator("#n").focus(); page.locator("#n").click(); wait_say(page, "Глава 3 из 3"); assert page.evaluate("document.activeElement.id") == "n"


def test_in_content_next_button_moves_focus_to_heading(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    page.locator("#v").get_by_role("button", name="Следующая глава").click(); wait_say(page, "Глава 2 из 3"); assert page.evaluate("document.activeElement.id") == "ch"


def test_zoom_keys_use_single_live_region(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); zv = lambda: " ".join(page.locator("#zv").inner_text().split())
    page.keyboard.press("+"); assert zv() == "Масштаб 110 %" and say(page) == ""
    page.keyboard.press("-"); page.keyboard.press("-"); assert zv() == "Масштаб 90 %"; page.keyboard.press("0"); assert zv() == "Масштаб 100 %"
    page.keyboard.press("="); assert zv() == "Масштаб 110 %"


def test_zoom_limit_is_announced(server, page):
    i = server.add_manga("М"); open_reader(page, server, i)
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'width', zoom: 200}))"); page.reload(); page.wait_for_selector("#v img")
    page.keyboard.press("+"); wait_say(page, "Масштаб 200 %, предел")


def test_fit_keys_announce_and_sync_radios(server, page):
    i = server.add_manga("М"); open_reader(page, server, i)
    for key, name in (("h", "По высоте"), ("o", "Исходный размер"), ("w", "По ширине")):
        page.keyboard.press(key); wait_say(page, name); assert page.get_by_role("radio", name=name).get_attribute("aria-checked") == "true"


def test_arrows_belong_to_browser_in_orig_mode_with_hscroll_but_p_n_work(server, page):
    i = server.add_manga("М", chapters=3); page.set_viewport_size({"width": 400, "height": 700}); open_reader(page, server, i); page.keyboard.press("o")
    assert page.evaluate("document.getElementById('v').scrollWidth > document.getElementById('v').clientWidth")
    page.keyboard.press("ArrowRight"); page.wait_for_timeout(300); assert cur_chapter(page) == 0
    page.keyboard.press("n"); wait_say(page, "Глава 2 из 3"); assert cur_chapter(page) == 1


def test_arrows_work_in_orig_mode_without_hscroll(server, page):
    i = server.add_manga("М", chapters=3); page.set_viewport_size({"width": 1600, "height": 900}); open_reader(page, server, i); page.keyboard.press("o")
    assert not page.evaluate("document.getElementById('v').scrollWidth > document.getElementById('v').clientWidth")
    page.keyboard.press("ArrowRight"); wait_say(page, "Глава 2 из 3")


def test_scroll_keys_not_intercepted(server, page):
    i = server.add_manga("М", pages=6); open_reader(page, server, i)
    page.evaluate("window.__dp = []; addEventListener('keydown', e => window.__dp.push([e.key, e.defaultPrevented]))")
    for k in ("Space", "PageDown", "PageUp", "ArrowDown", "Home", "End"): page.keyboard.press(k)
    got = page.evaluate("window.__dp"); assert len(got) == 6 and not any(d for _, d in got)


def test_keys_off_modifiers_select_and_dialog_ignored(server, page):
    i = server.add_manga("М", chapters=3); set_prefs(page, keys=False); open_reader(page, server, i)
    for k in "nwho+?": page.keyboard.press(k)
    page.wait_for_timeout(300); assert cur_chapter(page) == 0 and not page.locator("#helpDlg").is_visible() and say(page) == ""
    p = page.context.new_page(); open_reader(p, server, i); p.keyboard.press("Control+n"); p.keyboard.press("Alt+ArrowRight"); p.wait_for_timeout(300); assert cur_chapter(p) == 0
    p.locator("#c").focus(); p.keyboard.press("n"); p.wait_for_timeout(300); assert cur_chapter(p) == 0


def test_keys_do_nothing_while_help_is_open(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i); page.keyboard.press("?"); page.keyboard.press("n"); page.wait_for_timeout(300)
    assert cur_chapter(page) == 0 and page.locator("#helpDlg").is_visible()


def test_question_mark_opens_help_and_button_too(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); page.keyboard.press("?"); assert page.locator("#helpDlg").is_visible() and page.locator("#helpDlg caption").count() == 1
    page.keyboard.press("Escape"); assert not page.locator("#helpDlg").is_visible()
    page.get_by_role("button", name="Справка").click(); assert page.get_by_role("dialog").is_visible()
    page.get_by_role("button", name="Закрыть").click(); assert page.evaluate("document.activeElement.id") == "helpBtn"


def test_cyrillic_layout_falls_back_to_physical_key(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    page.evaluate("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'т', code: 'KeyN', bubbles: true}))"); wait_say(page, "Глава 2 из 3")


def test_chapter_change_still_saves_progress(server, page):
    i = server.add_manga("М", chapters=2, pages=3); open_reader(page, server, i)
    page.keyboard.press("n"); wait_say(page, "Глава 2 из 2"); page.mouse.wheel(0, 600); page.wait_for_timeout(1200)
    assert json.loads(server.get(f"/api/manga/{i}")[2])["progress"]["cid"] == "101"


def test_reader_key_action_pure(server, page):
    page.goto(server.url)
    r = page.evaluate("""import('/js/reader/modes.js').then(m => { const c = {hScroll: false}; return [
        m.keyAction({key: 'n'}, c), m.keyAction({key: 'ArrowLeft'}, c), m.keyAction({key: 'ArrowLeft'}, {hScroll: true}), m.keyAction({key: 'p'}, {hScroll: true}),
        m.keyAction({key: '+'}, c), m.keyAction({key: '='}, c), m.keyAction({key: '-'}, c), m.keyAction({key: '0'}, c), m.keyAction({key: 'h'}, c), m.keyAction({key: '?'}, c),
        m.keyAction({key: 'n', ctrlKey: true}, c), m.keyAction({key: 'x'}, c), m.keyAction({key: ' '}, c), m.keyAction({key: 'т', code: 'KeyN'}, c)] })""")
    assert r == ["next", "prev", None, "prev", "zoom+", "zoom+", "zoom-", "zoom0", "fit:height", "help", None, None, None, "next"]


def test_focused_chapter_heading_is_visible_below_sticky_header(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i); page.keyboard.press("n"); wait_say(page, "Глава 2 из 3"); page.wait_for_timeout(300)
    r = page.evaluate("(() => { const b = document.getElementById('ch').getBoundingClientRect(); const h = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hdr')) || 0; return [b.top - h, b.bottom, innerHeight] })()")
    assert r[0] >= -2 and r[1] <= r[2]
