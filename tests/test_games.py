import json
from conftest import run_axe

GAME = "Игра"


def open_card(page, title=GAME):
    card = page.get_by_role("button", name=f"{title}: не скачано")
    card.wait_for()
    return card


def test_game_card_has_button_role_and_opens_panel(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page).press("Enter")
    assert page.locator("#gpanel").evaluate("e=>e.open")
    assert page.locator("#gpanel").get_by_role("heading", name=GAME).count() == 1


def test_space_also_opens_panel(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page).press("Space")
    assert page.locator("#gpanel").evaluate("e=>e.open")


def test_panel_traps_focus_and_returns_it(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    card = open_card(page)
    card.focus()
    card.press("Enter")
    for _ in range(40):
        page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('#gpanel')") is not None
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.dataset.id") is not None


def test_close_button_closes_and_returns_focus(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    card = open_card(page)
    card.click()
    page.locator("#gpanel").get_by_role("button", name="Закрыть").click()
    assert not page.locator("#gpanel").evaluate("e=>e.open")
    assert page.evaluate("document.activeElement.dataset.id") is not None


def test_backdrop_click_closes_panel(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page).click()
    page.mouse.click(1200, 400)
    assert not page.locator("#gpanel").evaluate("e=>e.open")


def test_games_tabs_arrow_navigation(server, page):
    page.goto(server.url + "/#games")
    tab = page.get_by_role("tab", name="Библиотека")
    tab.focus()
    page.keyboard.press("ArrowRight")
    assert page.get_by_role("tab", name="Версии и чистка").get_attribute("aria-selected") == "true"
    assert page.evaluate("document.getElementById('gtab-lib').classList.contains('hide')")
    page.keyboard.press("Home")
    assert page.get_by_role("tab", name="Библиотека").get_attribute("aria-selected") == "true"
    assert page.locator("#gtab-lib").get_attribute("role") == "tabpanel"


def test_filter_and_genre_chips_expose_pressed(server, page):
    server.add_item(title=GAME, kind="game", info={"meta": {"genres": ["Rpg"]}})
    page.goto(server.url + "/#games")
    open_card(page)
    f = page.locator("#gchips").get_by_role("button", name="Не скачано")
    assert f.get_attribute("aria-pressed") == "false"
    f.click()
    assert page.locator("#gchips").get_by_role("button", name="Не скачано").get_attribute("aria-pressed") == "true"
    page.locator("#gens").click()
    g = page.locator("#genl").get_by_role("button", name="Rpg")
    assert g.get_attribute("aria-pressed") == "false"
    g.click()
    assert page.locator("#genl").get_by_role("button", name="Rpg").get_attribute("aria-pressed") == "true"


def test_drop_game_from_panel(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page).click()
    page.locator("#gpanel").get_by_role("button", name="Убрать из библиотеки").click()
    page.wait_for_function("!document.getElementById('gpanel').open")
    page.wait_for_function("document.querySelectorAll('#ggrid [data-card]').length===0")


def test_panel_note_and_auto_switch_are_named(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page).click()
    assert page.get_by_label("Заметка").count() == 1
    assert page.get_by_role("switch", name="Следить за новыми версиями").count() == 1


def test_add_game_without_link_reports_on_field(server, page):
    page.goto(server.url + "/#games")
    page.get_by_role("button", name="Добавить игру").click()
    assert page.locator("#gadd").get_attribute("aria-invalid") == "true"


def test_no_inline_handlers_and_no_article_buttons(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page)
    assert page.evaluate("document.querySelectorAll('#v-games [onclick], article[tabindex]').length") == 0


def test_legacy_script_is_gone(server, page):
    assert page.request.get(server.url + "/js/legacy.js").status == 404
    page.goto(server.url)
    assert page.evaluate("document.querySelectorAll('script:not([src]):not([type])').length") <= 1  # только ранний скрипт режимов


def test_games_axe_clean(server, page):
    server.add_item(title=GAME, kind="game")
    page.goto(server.url + "/#games")
    open_card(page)
    assert run_axe(page) == []
