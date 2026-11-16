import json


def test_add_media_serves_real_wav_with_range(server):
    i = server.add_media("Звук", "audio", seconds=1)
    s, h, b = server.get(f"/f/{i}", {"Range": "bytes=0-11"})
    assert s == 206 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def test_chromium_plays_wav_in_video_element(server, page):
    i = server.add_media("Ролик", "video", seconds=2); page.goto(server.url)
    d = page.evaluate("""id => new Promise((ok, no) => { const v = document.createElement('video'); v.preload = 'metadata';
        v.onloadedmetadata = () => ok(v.duration); v.onerror = () => no(String(v.error && v.error.code)); v.src = '/f/' + id })""", i)
    assert 1.5 < d < 2.5


def test_add_manga_writes_manifest_pages_and_row(server):
    i = server.add_manga("Манга", chapters=2, pages=3)
    s, _, b = server.get(f"/api/manga/{i}"); d = json.loads(b)
    assert s == 200 and d["have"] == 2 and len(d["chapters"][0]["files"]) == 3
    assert server.get(f"/mi/{i}/{d['chapters'][0]['id']}/001.png")[0] == 200


def test_two_manga_do_not_share_root(server):
    a, b = server.add_manga("А"), server.add_manga("Б")
    assert json.loads(server.get(f"/api/manga/{a}")[2])["title"] == "А"
    assert json.loads(server.get(f"/api/manga/{b}")[2])["title"] == "Б"


def test_media_subs_and_dir(server):
    i = server.add_media("Фильм", "video", subs={"ru.srt": b"x"})
    assert (server.media_dir(i) / "Фильм.ru.srt").read_bytes() == b"x"


def test_fresh_db_fixture_runs_for_server_only_tests_part1(server):
    server.add_media("leak", "audio")


def test_fresh_db_fixture_runs_for_server_only_tests_part2(server):
    s, _, b = server.get("/api/library")
    assert [x for x in json.loads(b) if x["title"] == "leak"] == []
