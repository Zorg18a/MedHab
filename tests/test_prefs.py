def test_prefs_applied_before_domcontentloaded(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs', JSON.stringify({scale:150, contrast:'high', theme:'light', targets:'large'}))")
    page.add_init_script("document.addEventListener('DOMContentLoaded',()=>window.__a=document.documentElement.dataset.scale)")
    page.goto(server.url)
    assert page.evaluate("window.__a") == "150"
    assert page.evaluate("getComputedStyle(document.documentElement).fontSize") == "24px"


def test_corrupted_json_falls_back_to_defaults(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs','{broken')")
    page.goto(server.url)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"


def test_storage_blocked_does_not_break(server, page):
    page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked')}})")
    errors = []
    page.on("pageerror", lambda e: errors.append(e))
    page.goto(server.url)
    assert not errors and page.locator("nav a").count() == 6


def test_save_prefs_roundtrip(server, page):
    page.goto(server.url)
    assert page.evaluate("MH.prefs.savePrefs({scale:125}).scale") == 125
    page.reload()
    assert page.evaluate("document.documentElement.dataset.scale") == "125"


def test_invalid_values_are_ignored(server, page):
    page.goto(server.url)
    assert page.evaluate("MH.prefs.savePrefs({scale:999, contrast:'x', theme:'pink'})") == {"scale": 100, "contrast": "normal", "theme": "dark", "targets": "normal", "keys": True}


def test_system_theme_resolves_via_media_query(server, page):
    page.emulate_media(color_scheme="light")
    page.add_init_script("localStorage.setItem('mh.prefs', JSON.stringify({theme:'system'}))")
    page.goto(server.url)
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
