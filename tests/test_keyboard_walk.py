import pytest
from conftest import ALL_VIEWS, open_any, open_seeded, set_prefs

EXPECTED_JS = """
(() => {
  const sel = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=radio], [role=switch], [tabindex]';
  return [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && e.tabIndex >= 0 && !e.disabled && !e.closest('[inert], dialog:not([open]), iframe')).length;
})()
"""

STEP_JS = """
(() => {
  const e = document.activeElement; if (!e || e === document.body) return null;
  e.dataset.walked = '1';
  const s = getComputedStyle(e);
  const focus = getComputedStyle(document.documentElement).getPropertyValue('--focus').trim();
  const hex = focus.replace('#', ''), rgb = 'rgb(' + [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)).join(', ') + ')';
  const ring = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  const shadow = s.boxShadow !== 'none';
  const border = /^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) && s.borderTopColor === rgb;
  // Фокус внутри нативной панели <video|audio controls>: activeElement остаётся элементом, но :focus не совпадает.
  // Кольцо там рисует сам браузер (проверено по скриншоту в Chromium); стилями хоста его не увидеть.
  const native = /^(VIDEO|AUDIO)$/.test(e.tagName) && !e.matches(':focus');
  return { ok: ring || shadow || border || native, d: e.tagName + '#' + e.id + '.' + e.className, first: e.classList.contains('skip') };
})()
"""


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_tab_reaches_every_control_with_visible_focus(server, page, view):
    open_any(page, server, view)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    expected = page.evaluate(EXPECTED_JS)
    invisible, seen = [], 0
    for _ in range(expected + 25):
        page.keyboard.press("Tab")
        r = page.evaluate(STEP_JS)
        if r is None:
            break
        seen += 1
        if not r["ok"]:
            invisible.append(r["d"])
        if seen > 3 and r["first"]:
            break
    missed = page.evaluate("""[...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=radio], [role=switch]')]
        .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && e.tabIndex >= 0 && !e.disabled && !e.closest('[inert], dialog:not([open]), iframe') && !e.dataset.walked)
        .map(e => e.tagName + '#' + e.id + '.' + e.className).slice(0, 10)""")
    assert missed == [], missed
    assert invisible == [], invisible


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_focus_visible_in_light_high_contrast(server, page, view):
    set_prefs(page, theme="light", contrast="high")
    open_any(page, server, view)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    for _ in range(12):
        page.keyboard.press("Tab")
        r = page.evaluate(STEP_JS)
        assert r is None or r["ok"], r


def test_shift_tab_goes_back_and_dialog_has_no_trap_exit_issue(server, page):
    open_seeded(page, server, "library")
    page.keyboard.press("Tab"); page.keyboard.press("Tab")
    first = page.evaluate("document.activeElement.outerHTML.slice(0,60)")
    page.keyboard.press("Tab"); page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.outerHTML.slice(0,60)") == first
    page.get_by_role("button", name="Добавить", exact=True).click()
    for _ in range(60):
        page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('#addDlg') !== null")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.id") == "addBtn"
