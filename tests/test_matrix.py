import pytest
from conftest import ALL_VIEWS, open_any, run_axe, set_prefs

COMBOS = [(t, c) for t in ("dark", "light") for c in ("normal", "high")]

CONTRAST_JS = """
(() => {
  const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 }; };
  const lum = ({ r, g, b }) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const bgOf = el => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none') return null;           // градиент или картинка: расчёт невозможен
      const c = parse(s.backgroundColor); if (c.a > 0) layers.push(c); if (c.a >= .99) break;
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (const c of layers.reverse()) base = over(c, base);
    return base;
  };
  const dimmed = el => { for (let e = el; e; e = e.parentElement) { if (+getComputedStyle(e).opacity < 1 || e.disabled) return true; } return false; };
  const out = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!(el.offsetParent || getComputedStyle(el).position === 'fixed')) continue;
    if (el.closest('dialog:not([open]), .hide, .vh')) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own || dimmed(el)) continue;
    const s = getComputedStyle(el), bg = bgOf(el); if (!bg) continue;
    const fg = over(parse(s.color), bg), L1 = lum(fg), L2 = lum(bg);
    const r = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    const px = parseFloat(s.fontSize), big = px >= 24 || (px >= 18.66 && +s.fontWeight >= 700);
    if (r < (big ? 3 : 4.5)) out.push({ t: el.textContent.trim().slice(0, 30), cls: el.className, r: Math.round(r * 100) / 100 });
  }
  return out.slice(0, 12);
})()
"""


@pytest.mark.parametrize("view", ALL_VIEWS)
@pytest.mark.parametrize("theme,contrast", COMBOS)
def test_text_contrast_in_rendered_page(server, page, view, theme, contrast):
    set_prefs(page, theme=theme, contrast=contrast)
    open_any(page, server, view)
    assert page.evaluate(CONTRAST_JS) == []


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_reflow_at_320_css_px(server, page, view):
    # WCAG 1.4.10: без горизонтальной прокрутки при ширине 320 CSS px (это 400 % от 1280)
    page.set_viewport_size({"width": 320, "height": 512})
    open_any(page, server, view)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), page.evaluate("document.documentElement.scrollWidth")


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_large_targets_min_44(server, page, view):
    set_prefs(page, targets="large")
    open_any(page, server, view)
    small = page.evaluate("""[...document.querySelectorAll('main button, main summary, main select, main [role=button], main input.sw, main .chip, main .gchip, nav a, .bell, .addbtn, body > header a, body > header button, body > header select')]
        .filter(e => e.offsetParent && !e.closest('.vh')).map(e => [e, e.getBoundingClientRect()]).filter(([e, r]) => r.width < 43.5 || r.height < 43.5)
        .map(([e, r]) => e.outerHTML.slice(0, 70) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height))""")
    assert small == []


def test_axe_matrix(server, page):
    for view in ALL_VIEWS:
        for theme, contrast in COMBOS:
            p = page.context.new_page()
            set_prefs(p, theme=theme, contrast=contrast)
            open_any(p, server, view)
            v = run_axe(p)
            p.close()
            assert v == [], (view, theme, contrast, v)
