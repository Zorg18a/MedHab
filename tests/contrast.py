import re
from pathlib import Path

HEX = re.compile(r"^#([0-9a-fA-F]{6})$")


def _lum(h):
    h = h.lstrip("#"); ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return .2126 * f(ch[0]) + .7152 * f(ch[1]) + .0722 * f(ch[2])


def ratio(fg, bg):
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + .05) / (b + .05)


def _blocks(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def load_tokens(css, theme, contrast):
    """Токены для сочетания темы и контраста: база, затем тема, затем контраст, затем их сочетание."""
    want = [":root", f":root[data-theme={theme}]", f":root[data-contrast={contrast}]", f":root[data-theme={theme}][data-contrast={contrast}]"]
    out = {}
    for sel in want:
        for s, body in _blocks(css):
            if s.replace('"', "").replace(" ", "") == sel:
                for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);?", body): out[k] = v.strip()
    return out


def hexes(tokens):
    return {k: v for k, v in tokens.items() if HEX.match(v)}


def read_tokens_css(root=None):
    return (Path(root or Path(__file__).resolve().parent.parent) / "css" / "tokens.css").read_text("utf-8")
