import pytest
from conftest import ALL_VIEWS, open_any

# Имя элемента (упрощённо, как его видит скринридер): aria-label, aria-labelledby, label, текст, alt вложенного img, title.
NAME_JS = """
(() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
  const name = e => {
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label').trim();
    const lb = e.getAttribute('aria-labelledby');
    if (lb) return lb.split(' ').map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim();
    if (e.labels && e.labels.length) return [...e.labels].map(l => l.textContent).join(' ').trim();
    const t = (e.textContent || '').trim(); if (t) return t;
    const im = e.querySelector('img[alt]'); if (im && im.alt.trim()) return im.alt.trim();
    return (e.getAttribute('title') || '').trim();
  };
  const sel = 'button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=radio], [role=switch], [role=progressbar], summary';
  const bad = [...document.querySelectorAll(sel)].filter(e => vis(e) && !e.closest('dialog:not([open])') && !name(e)).map(e => e.outerHTML.slice(0, 110));
  return bad;
})()
"""


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_every_visible_control_has_a_name(server, page, view):
    open_any(page, server, view)
    assert page.evaluate(NAME_JS) == []


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_structure_rules(server, page, view):
    open_any(page, server, view)
    r = page.evaluate("""(() => {
      const out = {};
      const ids = [...document.querySelectorAll('[id]')].map(e => e.id); out.dupIds = ids.filter((x, i) => ids.indexOf(x) !== i);
      out.brokenRefs = [...document.querySelectorAll('[aria-describedby],[aria-controls],[aria-labelledby]')].flatMap(e =>
        ['aria-describedby','aria-controls','aria-labelledby'].flatMap(a => (e.getAttribute(a)||'').split(' ').filter(Boolean).filter(i => !document.getElementById(i)).map(i => a+'→'+i)));
      out.inline = document.querySelectorAll('[onclick],[onchange],[oninput]').length;
      out.chipsNoPressed = [...document.querySelectorAll('.chip,.gchip')].filter(e => !e.hasAttribute('aria-pressed')).length;
      out.imgNoAlt = [...document.querySelectorAll('img:not([alt])')].length;
      out.h1 = [...document.querySelectorAll('h1')].filter(e => e.offsetParent !== null).length;
      out.lang = document.documentElement.lang;
      out.progress = [...document.querySelectorAll('[role=progressbar]')].filter(e => !e.hasAttribute('aria-valuenow')).length;
      out.tabindexPositive = [...document.querySelectorAll('[tabindex]')].filter(e => +e.getAttribute('tabindex') > 0).length;
      return out;
    })()""")
    assert r["dupIds"] == [] and r["brokenRefs"] == [], r
    assert r["inline"] == 0 and r["chipsNoPressed"] == 0 and r["imgNoAlt"] == 0 and r["progress"] == 0 and r["tabindexPositive"] == 0, r
    assert r["h1"] == 1 and r["lang"] == "ru", r
