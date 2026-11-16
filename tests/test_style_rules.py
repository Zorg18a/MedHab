"""Статическая проверка правил стиля для файлов этапа 2 (без inline-обработчиков, шрифты в rem, цвета токенами)."""
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = ["player.html", "css/player.css", "js/player/player.js", "js/player/keys.js", "reader.html", "js/reader/reader.js", "js/reader/modes.js", "js/views/continue.js"]


@pytest.mark.parametrize("f", FILES)
def test_no_inline_handlers(f):
    assert (ROOT / f).exists(), f
    assert not re.search(r"""\son(click|change|input|keydown|keyup|load|error|submit)\s*=""", (ROOT / f).read_text("utf-8"))


@pytest.mark.parametrize("f", [x for x in FILES if x.endswith((".css", ".html"))])
def test_no_px_font_sizes(f):
    assert not re.search(r"font-size\s*:\s*[\d.]+px", (ROOT / f).read_text("utf-8"))


def test_player_css_uses_tokens_only():
    css = (ROOT / "css/player.css").read_text("utf-8")
    assert css and not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\b(rgb|hsl)a?\(", css)
