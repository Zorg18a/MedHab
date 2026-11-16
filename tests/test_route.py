import pytest

VIEWS = {"library": "Библиотека", "inbox": "Входящие", "downloads": "Загрузки", "games": "Игры", "settings": "Настройки"}


@pytest.mark.parametrize("view,name", VIEWS.items())
def test_title_on_initial_load(server, page, view, name):
    page.goto(server.url + "/#" + view)
    assert page.title() == f"{name} — MediaHub"


@pytest.mark.parametrize("view,name", VIEWS.items())
def test_route_change_focuses_heading(server, page, view, name):
    start = "games" if view == "downloads" else "downloads"
    page.goto(server.url + "/#" + start)
    page.evaluate(f"location.hash='#{view}'")
    page.wait_for_function(f"document.title.startsWith('{name}')")
    assert page.evaluate("document.activeElement.tagName") == "H1"
    assert page.evaluate("document.activeElement.textContent.trim()") == name


def test_initial_load_does_not_steal_focus(server, page):
    page.goto(server.url + "/#settings")
    assert page.evaluate("document.activeElement.tagName") == "BODY"


def test_skip_link_is_first_tab_stop_and_moves_focus(server, page):
    page.goto(server.url)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Перейти к содержимому"
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main"
    assert page.url.endswith("/") or "#" not in page.url


def test_api_failure_reports_offline_without_unhandled_rejection(server, page):
    errors = []
    page.on("pageerror", lambda e: errors.append(e))
    page.goto(server.url)
    page.route("**/api/jobs", lambda r: r.abort())
    page.wait_for_timeout(2500)
    assert not errors
    assert page.evaluate("MH.__online") is False
