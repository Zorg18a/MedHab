import json
import re
from conftest import open_player


def seed(server, n=3):
    ids = [server.add_media(f"Фильм {k}", "video") for k in range(n)]
    for k, i in enumerate(ids): server.set_pos(i, 30, 600, updated=1000 + k)
    return ids[::-1]                           # порядок на странице: свежие первыми


def say(page): return page.locator("#mh-live-polite").inner_text().strip()


def remove_btn(page, title): return page.get_by_role("button", name=f"Убрать из «Продолжить»: {title}")


def test_block_hidden_when_nothing_to_continue(server, page):
    server.add_media("a", "video"); page.goto(server.url); page.wait_for_selector(".cv"); assert page.locator("#contH").count() == 0


def test_block_appears_after_position_is_saved(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i)
    with page.expect_request("**/api/play/pos"): page.evaluate("m.currentTime = 20; m.play().then(() => m.pause())")
    page.goto(server.url); page.wait_for_selector("#contH"); assert page.locator("section[aria-labelledby=contH] li").count() == 1


def test_markup_progressbar_and_label(server, page):
    [i] = seed(server, 1); page.goto(server.url); page.wait_for_selector("#contH"); s = page.locator("section[aria-labelledby=contH]")
    pb = s.get_by_role("progressbar", name="Просмотрено"); assert pb.get_attribute("aria-valuenow") == "5" and "осталось" in s.inner_text()
    assert s.get_by_role("link", name="Продолжить: Фильм 0").get_attribute("href") == f"/p/{i}"
    assert s.locator("h3").count() == 1 and s.locator("h2").inner_text() == "Продолжить" and s.locator("li > article.c").count() == 1


def test_titles_escaped(server, page):
    i = server.add_media('"><img src=x onerror=window.__x=1> <b>Тест</b>', "video"); server.set_pos(i, 30, 600); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.evaluate("window.__x") is None and page.locator("#cont b").count() == 0 and page.locator("#cont img[src=x]").count() == 0


def test_hidden_while_searching_and_with_filter_and_back(server, page):
    seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    page.fill("#q", "Фильм 1"); page.wait_for_selector("#contH", state="hidden")
    page.fill("#q", ""); page.wait_for_selector("#contH", state="visible")
    page.get_by_role("button", name=re.compile("^Видео")).click(); page.wait_for_selector("#contH", state="hidden")
    page.get_by_role("button", name=re.compile("^Все")).click(); page.wait_for_selector("#contH", state="visible")


def test_remove_moves_focus_to_next_card_announces_and_forgets(server, page):
    a, b, c = seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    remove_btn(page, "Фильм 2").click(); page.wait_for_function("document.querySelectorAll('#cont li').length === 2")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Продолжить: Фильм 1" and say(page) == "Убрано из «Продолжить»"
    assert json.loads(server.get(f"/api/play/{a}")[2])["pos"] == 0


def test_remove_last_card_focuses_heading_and_only_card_focuses_h1(server, page):
    seed(server, 2); page.goto(server.url); page.wait_for_selector("#contH")
    remove_btn(page, "Фильм 0").click(); page.wait_for_function("document.querySelectorAll('#cont li').length === 1")
    assert page.evaluate("document.activeElement.id") == "contH"
    remove_btn(page, "Фильм 1").click(); page.wait_for_selector("#contH", state="detached"); assert page.evaluate("document.activeElement.tagName") == "H1"


def test_item_stays_in_library_grid_after_remove(server, page):
    seed(server, 1); page.goto(server.url); page.wait_for_selector("#contH"); remove_btn(page, "Фильм 0").click(); page.wait_for_selector("#contH", state="detached")
    assert page.get_by_role("link", name="Открыть: Фильм 0").count() == 1


def test_cards_join_j_k_navigation(server, page):
    seed(server, 2); page.goto(server.url); page.wait_for_selector("#contH"); page.keyboard.press("j")
    assert page.evaluate("document.activeElement.closest('#cont') !== null")


def test_no_anchor_hash_links_and_no_inline_handlers_in_block(server, page):
    seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.evaluate("document.querySelectorAll('#cont a[href^=\"#\"], #cont [onclick]').length") == 0


def test_manga_card_links_to_reader_with_chapter_label(server, page):
    m = server.add_manga("Манга", chapters=3, pages=20, progress=(1, 13), updated=5); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.get_by_role("link", name="Продолжить: Манга").get_attribute("href") == f"/m/{m}" and "стр. 14" in page.locator("#cont").inner_text()


def test_block_refreshes_when_the_tab_becomes_visible_again(server, page):
    page.goto(server.url); page.wait_for_selector("#lib"); assert page.locator("#contH").count() == 0
    i = server.add_media("Новый", "video"); server.set_pos(i, 30, 600)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); page.wait_for_selector("#contH")


def test_unchanged_data_does_not_rerender_and_lose_focus(server, page):
    seed(server, 2); page.goto(server.url); page.wait_for_selector("#contH"); page.locator("#cont .cv").first.focus()
    page.evaluate("document.getElementById('q').dispatchEvent(new Event('input')); document.dispatchEvent(new Event('visibilitychange'))"); page.wait_for_timeout(700)
    assert page.evaluate("document.activeElement.classList.contains('cv') && !!document.activeElement.closest('#cont')")


def test_block_is_rendered_and_fits_320(server, touch_page):
    seed(server); touch_page.set_viewport_size({"width": 320, "height": 640}); touch_page.goto(server.url); touch_page.wait_for_selector("#contH")
    assert touch_page.locator("#cont .c").first.bounding_box()["width"] > 100 and touch_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_continue_html_pure(server, page):
    page.goto(server.url)
    r = page.evaluate("""import('/js/views/continue.js').then(m => [m.continueHtml([]), m.continueHtml([{id: 1, kind: 'video', title: 'A', cover: '', open: '/p/1', pct: 40, label: 'осталось 5 мин'}]).includes('aria-valuenow="40"')])""")
    assert r == ["", True]
