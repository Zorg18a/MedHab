import pytest
from contrast import ratio, load_tokens, hexes, read_tokens_css


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("contrast", ["normal", "high"])
def test_token_pairs_meet_wcag(theme, contrast):
    t = hexes(load_tokens(read_tokens_css(), theme, contrast))
    grounds = [t["ink"], t["panel"], t["raise"]]
    for fg in ("text", "mute", "ph", "danger", "ok", "amber-fg"):
        for bg in grounds:
            assert ratio(t[fg], bg) >= 4.5, (fg, bg)
    for bg in (t["ink"], t["panel"]):
        assert ratio(t["edge"], bg) >= 3, ("edge", bg)
    for bg in grounds:
        assert ratio(t["focus"], bg) >= 3, ("focus", bg)
    assert ratio(t["amber-ink"], t["amber"]) >= 4.5


def test_ratio_known_value():
    assert round(ratio("#6d748a", "#1a1e2a"), 2) == 3.57  # старый placeholder (пункт 1 аудита)
