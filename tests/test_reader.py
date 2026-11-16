from conftest import run_axe, set_prefs


def test_reader_chapter_select_has_name(server, page):
    page.goto(server.url + "/m/999")
    assert page.locator("select#c").get_attribute("aria-label") == "Глава"


def test_reader_axe_clean(server, page):
    page.goto(server.url + "/m/999")
    assert run_axe(page) == []


def test_reader_landmarks_and_heading(server, page):
    page.goto(server.url + "/m/999")
    assert page.locator("main").count() == 1 and page.locator("h1").count() == 1
    assert page.get_by_role("heading", level=1).inner_text().strip() != ""


def test_reader_nav_buttons_have_clear_names(server, page):
    page.goto(server.url + "/m/999")
    assert page.get_by_role("button", name="Пред. глава").count() == 1
    assert page.get_by_role("button", name="След. глава").count() == 1


def test_reader_uses_shared_tokens(server, page):
    page.goto(server.url + "/m/999")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--edge').trim()") != ""


def test_reader_respects_display_prefs(server, page):
    set_prefs(page, theme="light", scale=125)
    page.goto(server.url + "/m/999")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("getComputedStyle(document.documentElement).fontSize") == "20px"
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg != "rgb(13, 15, 20)"


def test_reader_header_text_contrast_in_all_themes(server, page):
    from contrast import ratio
    for theme in ("dark", "light"):
        ctx = page.context
        p = ctx.new_page()
        p.add_init_script(f"localStorage.setItem('mh.prefs', JSON.stringify({{theme:'{theme}'}}))")
        p.goto(server.url + "/m/999")
        fg, bg = p.evaluate("""(()=>{const c=s=>{const m=s.match(/\\d+/g).map(Number);return '#'+m.slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('')};
          return [c(getComputedStyle(document.querySelector('header a')).color), c(getComputedStyle(document.body).backgroundColor)]})()""")
        assert ratio(fg, bg) >= 4.5, (theme, fg, bg)
        p.close()
