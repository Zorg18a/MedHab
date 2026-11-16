import json
from conftest import stub_inbox, run_axe


def test_row_checkboxes_have_distinct_names(server, page):
    stub_inbox(page, ["Альфа", "Бета"])
    page.goto(server.url + "/#inbox")
    assert page.get_by_role("checkbox", name="Включить в план: Альфа").count() == 1
    assert page.get_by_role("checkbox", name="Включить в план: Бета").count() == 1


def test_selects_name_their_row(server, page):
    stub_inbox(page, ["Альфа", "Бета"])
    page.goto(server.url + "/#inbox")
    assert page.get_by_label("Тип материала: Альфа").count() == 1
    assert page.get_by_label("Что сделать: Бета").count() == 1


def test_filter_chips_pressed_and_summary_live(server, page):
    stub_inbox(page, ["Альфа", "Бета"])
    page.goto(server.url + "/#inbox")
    assert page.locator(".bsum").get_attribute("aria-live") == "polite"
    page.get_by_role("checkbox", name="Включить в план: Альфа").uncheck()
    assert "Выбрано 1 из 2" in page.locator(".bsum").inner_text()
    c = page.get_by_role("button", name="Новое")
    assert c.get_attribute("aria-pressed") == "false"
    c.click()
    assert page.get_by_role("button", name="Новое").get_attribute("aria-pressed") == "true"
    assert page.evaluate("document.activeElement.textContent.startsWith('Новое')")


def test_confirm_sends_plan_and_offers_downloads(server, page):
    sent = []
    page.route("**/api/inbox/confirm", lambda r: (sent.append(json.loads(r.request.post_data)), r.fulfill(status=200, content_type="application/json", body=json.dumps({"download": 2, "links": 0}))))
    stub_inbox(page, ["Альфа", "Бета"])
    page.goto(server.url + "/#inbox")
    page.get_by_role("button", name="Добавить в очередь").click()
    page.wait_for_function("document.getElementById('mh-live-polite').textContent.includes('В очереди: 2')")
    assert str(sent[0]["batch"]) == "1" and [r["id"] for r in sent[0]["rows"]] == [1, 2] and all(r["action"] == "download" for r in sent[0]["rows"])
    assert page.locator(".toast").get_by_role("button", name="Загрузки").count() == 1


def test_pair_bar_approve(server, page):
    sent = []
    page.route("**/api/ext", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"pending": [{"origin": "chrome-extension://abc", "name": "MediaHub"}], "paired": [], "ext_dir": "/x", "ext_ff": "/y", "inbox_pending": 0})))
    page.route("**/api/ext/approve", lambda r: (sent.append(json.loads(r.request.post_data)), r.fulfill(status=200, content_type="application/json", body="{}")))
    page.goto(server.url)
    page.get_by_role("button", name="Разрешить").click()
    page.wait_for_timeout(300)
    assert sent == [{"origin": "chrome-extension://abc", "allow": True}]
    assert page.locator("#pairBar").get_attribute("role") == "alert"


def test_empty_inbox_shows_instructions(server, page):
    page.route("**/api/inbox", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"batches": []})))
    page.goto(server.url + "/#inbox")
    assert page.get_by_role("heading", name="Входящие пусты").count() == 1


def test_no_inline_handlers_in_inbox(server, page):
    stub_inbox(page, ["Альфа"])
    page.goto(server.url + "/#inbox")
    page.wait_for_selector(".ir")
    assert page.evaluate("document.querySelectorAll('#v-inbox [onclick], #pairBar [onclick]').length") == 0
    assert page.evaluate("document.querySelectorAll('#v-inbox [data-do]').length") == 0


def test_inbox_axe_clean(server, page):
    stub_inbox(page, ["Альфа"])
    page.goto(server.url + "/#inbox")
    page.wait_for_selector(".ir")
    assert run_axe(page) == []
