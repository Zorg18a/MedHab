import json
import pytest
from conftest import run_axe

SET = ["games_check_hours", "manga_via", "folder", "res", "afmt", "subs_on", "subs_langs", "thumbs", "skip", "workers",
       "limit_mb", "depth", "maxp", "videos", "show_browser", "cookie_file", "cookie_browser", "games_root"]


@pytest.mark.parametrize("key", SET)
def test_every_setting_has_accessible_name(server, page, key):
    page.goto(server.url + "/#settings")
    name = page.evaluate(f"(()=>{{const e=document.getElementById('s_{key}');return e.labels&&e.labels[0]?e.labels[0].textContent.trim():(e.getAttribute('aria-label')||'')}})()")
    assert name


def test_checkbox_settings_are_switches(server, page):
    page.goto(server.url + "/#settings")
    assert page.evaluate("[...document.querySelectorAll('#v-settings input.sw')].every(e=>e.getAttribute('role')==='switch')")


def test_scale_pref_changes_root_font_and_announces(server, page):
    page.goto(server.url + "/#settings")
    page.get_by_label("Размер текста").select_option("150")
    assert page.evaluate("getComputedStyle(document.documentElement).fontSize") == "24px"
    assert "Размер текста" in page.locator("#mh-live-polite").inner_text()


def test_contrast_theme_and_targets_apply(server, page):
    page.goto(server.url + "/#settings")
    page.get_by_label("Контраст").select_option("high")
    page.get_by_label("Тема оформления").select_option("light")
    page.get_by_role("switch", name="Крупные цели нажатия").check()
    d = page.evaluate("({...document.documentElement.dataset})")
    assert d["contrast"] == "high" and d["theme"] == "light" and d["targets"] == "large"
    page.reload()
    assert page.get_by_label("Тема оформления").input_value() == "light"


def test_hotkeys_switch_present_and_persists(server, page):
    page.goto(server.url + "/#settings")
    page.get_by_role("switch", name="Горячие клавиши").uncheck()
    page.reload()
    assert page.evaluate("JSON.parse(localStorage.getItem('mh.prefs')).keys") is False
    assert not page.get_by_role("switch", name="Горячие клавиши").is_checked()


def test_server_settings_still_save(server, page):
    page.goto(server.url + "/#settings")
    page.locator("#s_workers").fill("5")
    page.wait_for_timeout(900)
    assert json.loads(page.request.get(server.url + "/api/settings").text())["workers"] == 5


def test_settings_axe_clean(server, page):
    page.goto(server.url + "/#settings")
    assert run_axe(page) == []


def test_settings_rows_are_actually_rendered(server, page):
    page.goto(server.url + "/#settings")
    sizes = page.evaluate("[...document.querySelectorAll('#v-settings .sr')].map(e=>{const r=e.getBoundingClientRect();return [r.width,r.height]})")
    assert len(sizes) >= 24 and all(w > 100 and h > 20 for w, h in sizes)
    assert page.locator("#s_folder").is_visible() and page.locator("#d_keys").is_visible()
