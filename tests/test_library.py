EVIL = '"><img src=x onerror=window.__x=1> <b>Тест</b>'


def test_titles_are_escaped_in_labels(server, page):
    server.add_item(title=EVIL, kind="video")
    page.goto(server.url)
    page.wait_for_selector(".cv")
    assert page.evaluate("window.__x") is None
    assert page.locator("main b", has_text="Тест").count() == 0
    assert "<b>Тест</b>" in page.locator(".t").first.inner_text()


def test_kind_chips_expose_pressed(server, page):
    server.add_item(title="a", kind="video")
    page.goto(server.url)
    page.wait_for_selector(".chip")
    c = page.get_by_role("button", name="Видео")
    assert c.get_attribute("aria-pressed") == "false"
    c.click()
    assert page.get_by_role("button", name="Видео").get_attribute("aria-pressed") == "true"
    assert page.get_by_role("button", name="Все").get_attribute("aria-pressed") == "false"


def test_library_has_h1(server, page):
    page.goto(server.url)
    assert page.locator("#v-library h1").count() == 1


def test_add_error_is_tied_to_field(server, page):
    page.goto(server.url)
    page.get_by_role("button", name="Добавить", exact=True).click()
    page.get_by_role("button", name="Скачать", exact=True).click()
    f = page.locator("#urls")
    assert f.get_attribute("aria-invalid") == "true"
    assert page.evaluate("document.activeElement.id") == "urls"
    assert "ссылк" in page.locator("#" + f.get_attribute("aria-describedby")).inner_text()
    page.keyboard.type("x")
    assert f.get_attribute("aria-invalid") is None


def test_txt_picker_is_button_and_keyboard_operable(server, page):
    page.goto(server.url)
    page.get_by_role("button", name="Добавить", exact=True).click()
    page.locator("#more summary").click()
    with page.expect_file_chooser():
        page.get_by_role("button", name="Выбрать файл .txt").press("Enter")


def test_card_actions_visible_on_touch(server, touch_page):
    server.add_item(title="a", kind="video")
    touch_page.goto(server.url)
    touch_page.wait_for_selector(".act")
    assert touch_page.evaluate("getComputedStyle(document.querySelector('.act')).opacity") == "1"


def test_game_card_is_button_not_link(server, page):
    server.add_item(title="g", kind="game")
    page.goto(server.url)
    page.wait_for_selector(".cv")
    assert page.locator("a[href='#']").count() == 0
    assert page.locator("button.cv").count() == 1


def test_kind_radiogroup_arrow_keys(server, page):
    page.goto(server.url)
    page.get_by_role("button", name="Добавить", exact=True).click()
    page.get_by_role("radio", name="Видео").focus()
    page.keyboard.press("ArrowRight")
    assert page.get_by_role("radio", name="Аудио").get_attribute("aria-checked") == "true"
    assert page.evaluate("[...document.querySelectorAll('.seg [role=radio]')].map(r=>r.tabIndex)") == [-1, 0, -1, -1]


def test_library_actions_work_via_delegation(server, page):
    server.add_item(title="Удаляемый", kind="video")
    page.goto(server.url)
    page.wait_for_selector(".act")
    page.locator(".c").first.hover()
    page.get_by_role("button", name="Изменить").click()
    assert page.locator("#editDlg").evaluate("e=>e.open")
    page.get_by_role("button", name="Отмена").click()
    page.locator(".c").first.hover()
    page.get_by_role("button", name="Удалить").click()
    page.locator("#delDlg").get_by_role("button", name="Убрать из библиотеки").click()
    page.wait_for_function("document.querySelectorAll('.c').length===0")


def test_empty_state_buttons_open_add(server, page):
    page.goto(server.url)
    page.get_by_role("button", name="Добавить ссылку").click()
    assert page.locator("#addDlg").evaluate("e=>e.open")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Добавить ссылку"


def test_no_inline_handlers_left_in_library(server, page):
    server.add_item(title="a", kind="video")
    page.goto(server.url)
    page.wait_for_selector(".cv")
    assert page.evaluate("document.querySelectorAll('#v-library [onclick], #addDlg [onclick]').length") == 0
