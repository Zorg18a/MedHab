# Обложка игры: картинка из поста темы, а не логотип сайта из og:image.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gamelib

PAGE = '''<html><head><meta property="og:title" content="Hail Dicktator [v0.98.1] [Hachigames] | F95zone">
<meta property="og:image" content="https://f95zone.to/assets/images/logo-md.png"></head><body>
<h1 class="p-title-value"><span class="label">VN</span> Hail Dicktator</h1>
<picture><img src="/assets/images/logo-sm.png" alt="F95zone"></picture>
<div class="bbWrapper"><div class="bbImageWrapper js-lbImage" data-src="https://attachments.f95zone.to/2021/02/1044036_title.jpg">
<img src="data:image/gif;base64,R0lGOD" data-src="https://attachments.f95zone.to/2021/02/1044036_title.jpg" class="bbImage lazyload"></div>
<b>Overview:</b><br>Text.<br></div></body></html>'''
URL = 'https://f95zone.to/threads/hail-dicktator-v0-98-1-hachigames.51437/'


def test_cover_is_first_post_image_not_site_logo():
    assert gamelib.parse_thread(PAGE, URL)['cover'] == 'https://attachments.f95zone.to/2021/02/1044036_title.jpg'


def test_site_logo_from_og_image_is_never_used():
    page = PAGE.replace('data-src="https://attachments.f95zone.to/2021/02/1044036_title.jpg" class="bbImage lazyload"', '')
    assert gamelib.parse_thread(page, URL)['cover'] == ''


def test_build_date_versions_and_letter_suffix():
    # HiddenBadge_20260828c: дата сборки — это версия, а не часть названия; буква «c» новее «b»
    import gamesweep
    assert gamesweep.parse_name("HiddenBadge_20260828c")["key"] == gamesweep.parse_name("Hidden Badge")["key"] == "hiddenbadge"
    assert gamesweep.parse_name("HiddenBadge_20260828c.zip")["text"] == "20260828c"
    assert gamesweep.parse_name("Game 20261345")["nums"] is None                      # месяц 13: это не дата
    assert gamelib.newer("20260828c", "20260828b") and not gamelib.newer("20260828b", "20260828c")
    assert gamelib.newer("0.5b", "0.5") and not gamelib.newer("0.5", "0.5a") and not gamelib.newer("1.0", "1.0")
