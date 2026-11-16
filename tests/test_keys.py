def test_sequencer_pure(server, page):
    page.goto(server.url)
    r = page.evaluate("""import('/js/a11y/keys.js').then(m=>{const s=m.createSequencer(1500);
      return [s.feed('g',0), s.feed('l',100), s.feed('g',200), s.feed('d',2000), s.feed('g',3000), s.feed('n',3100), s.feed('g',4000), s.feed('g',4100)]})""")
    assert r == [None, "nav:library", None, None, None, "log", None, "nav:games"]


def test_g_then_d_navigates(server, page):
    page.goto(server.url)
    page.keyboard.press("g")
    page.keyboard.press("d")
    page.wait_for_function("location.hash==='#downloads'")


def test_ignored_in_inputs_and_with_modifiers(server, page):
    page.goto(server.url)
    page.locator("#q").focus()
    page.keyboard.type("gd")
    assert not page.url.endswith("#downloads") and page.input_value("#q") == "gd"
    page.locator("body").click()
    page.keyboard.press("Control+g")
    page.keyboard.press("d")
    page.keyboard.press("Alt+g")
    page.keyboard.press("l")
    assert not page.url.endswith("#downloads")


def test_switch_off_disables_keys(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs', JSON.stringify({keys:false}))")
    page.goto(server.url)
    page.keyboard.press("g")
    page.keyboard.press("d")
    page.keyboard.press("?")
    assert not page.url.endswith("#downloads")
    assert not page.locator("#helpDlg").is_visible()


def test_question_mark_opens_help_and_slash_focuses_search(server, page):
    page.goto(server.url)
    page.keyboard.press("?")
    assert page.locator("#helpDlg").is_visible()
    page.keyboard.press("Escape")
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "q"


def test_slash_from_other_view_goes_to_library_search(server, page):
    page.goto(server.url + "/#settings")
    page.keyboard.press("/")
    page.wait_for_function("document.activeElement.id==='q'")
    assert page.url.endswith("#library")


def test_help_can_turn_keys_off(server, page):
    page.goto(server.url)
    page.keyboard.press("?")
    page.get_by_role("button", name="Отключить горячие клавиши").click()
    assert page.evaluate("JSON.parse(localStorage.getItem('mh.prefs')).keys") is False


def test_j_k_move_between_cards(server, page):
    for i in range(3):
        server.add_item(title=f"Карточка {i}", kind="video")
    page.goto(server.url)
    page.wait_for_selector(".cv")
    page.keyboard.press("j")
    first = page.evaluate("document.activeElement.getAttribute('aria-label')")
    page.keyboard.press("j")
    second = page.evaluate("document.activeElement.getAttribute('aria-label')")
    assert first and second and first != second
    page.keyboard.press("k")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == first
