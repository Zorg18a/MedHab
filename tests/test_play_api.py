import json
import pytest


def play(server, i): return json.loads(server.get(f"/api/play/{i}")[2])


def test_play_fields(server):
    i = server.add_media("Лекция", "video")
    s, _, b = server.get(f"/api/play/{i}"); d = json.loads(b)
    assert s == 200 and d["id"] == i and d["title"] == "Лекция" and d["kind"] == "video"
    assert d["src"] == f"/f/{i}" and d["pos"] == 0 and d["dur"] == 0 and d["finished"] is False and d["subs"] == [] and d["cover"] == ""


@pytest.mark.parametrize("kind", ["manga", "game", "site", "link"])
def test_play_404_for_other_kinds(server, kind):
    assert server.get(f"/api/play/{server.add_item('x', kind)}")[0] == 404


def test_play_404_for_missing(server): assert server.get("/api/play/999999")[0] == 404


def test_pos_under_5s_not_saved(server):
    i = server.add_media("a", "audio")
    assert json.loads(server.post("/api/play/pos", {"id": i, "pos": 4.9, "dur": 100})[2])["saved"] is False
    assert play(server, i)["pos"] == 0
    server.post("/api/play/pos", {"id": i, "pos": 5, "dur": 100}); assert play(server, i)["pos"] == 5


@pytest.mark.parametrize("pos,dur,fin", [(90, 100, True), (89.9, 100, False), (9999, 0, False), (100, 100, True)])
def test_finished_rule(server, pos, dur, fin):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": pos, "dur": dur})
    assert play(server, i)["finished"] is fin


@pytest.mark.parametrize("body", ['{"id":%d,"pos":NaN,"dur":0}', '{"id":%d,"pos":-3,"dur":0}', '{"id":%d,"pos":"7","dur":"x"}', '{"id":%d,"pos":Infinity,"dur":1}'])
def test_bad_numbers_rejected_and_not_stored(server, body):
    i = server.add_media("a", "audio"); assert server.post("/api/play/pos", body % i)[0] == 400
    assert play(server, i)["pos"] == 0


def test_pos_unknown_item_404(server): assert server.post("/api/play/pos", {"id": 999999, "pos": 30, "dur": 100})[0] == 404


def test_forget_removes_row(server):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}); server.post("/api/play/forget", {"id": i})
    assert play(server, i)["pos"] == 0


def test_delete_removes_playpos(server):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}); server.post("/api/delete", {"id": i})
    assert server._playpos_rows(i) == 0


def test_new_routes_keep_host_and_xmh_checks(server):
    i = server.add_media("a", "audio")
    assert server.get(f"/api/play/{i}", {"Host": "evil.example"})[0] == 403
    assert server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}, {"X-MH": ""})[0] == 403
    assert server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}, {"Origin": "http://evil.example"})[0] == 403
    assert server.post("/api/play/forget", {"id": i}, {"X-MH": ""})[0] == 403


def test_reset_clears_playpos_between_tests(server):
    i = server.add_media("a", "audio"); server.set_pos(i, 30, 100); server.reset()
    assert server._playpos_rows(i) == 0


# ---------- субтитры ----------
SRT = "1\n00:00:01,500 --> 00:00:03,000\nПривет, мир\n\n2\n00:00:04,000 --> 00:00:05,250\nВторая, реплика\n"


def vtt(server, i, n=0):
    s, h, b = server.get(f"/sub/{i}/{n}.vtt"); return s, h, b.decode("utf-8", "replace")


def test_srt_becomes_webvtt_and_text_commas_survive(server):
    i = server.add_media("a", "video", subs={"ru.srt": SRT.encode("utf-8")})
    s, h, t = vtt(server, i)
    assert s == 200 and h["Content-Type"].startswith("text/vtt") and t.startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.000" in t and "Привет, мир" in t and "Вторая, реплика" in t and ",500" not in t


def test_bom_stripped_and_cp1251_decoded(server):
    a = server.add_media("a", "video", subs={"ru.srt": b"\xef\xbb\xbf" + SRT.encode("utf-8")})
    b = server.add_media("b", "video", subs={"ru.srt": SRT.encode("cp1251")})
    assert "\ufeff" not in vtt(server, a)[2] and "Привет, мир" in vtt(server, b)[2]


def test_vtt_passthrough_gets_header_once(server):
    i = server.add_media("a", "video", subs={"en.vtt": b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n"})
    assert vtt(server, i)[2].count("WEBVTT") == 1


def test_vtt_without_header_gets_one(server):
    i = server.add_media("a", "video", subs={"en.vtt": b"00:00:01.000 --> 00:00:02.000\nHi\n"})
    assert vtt(server, i)[2].startswith("WEBVTT")


def test_subs_listing_order_labels_and_urls(server):
    i = server.add_media("a", "video", subs={"en.srt": SRT.encode(), "ru.srt": SRT.encode(), "de.srt": SRT.encode(), "srt": SRT.encode()})
    subs = play(server, i)["subs"]
    assert [(s["lang"], s["label"]) for s in subs] == [("", "Субтитры"), ("de", "de"), ("en", "English"), ("ru", "Русский")]
    assert [s["n"] for s in subs] == [0, 1, 2, 3] and subs[2]["url"] == f"/sub/{i}/2.vtt"


def test_neighbour_videos_in_same_folder_do_not_share_subs(server):
    a = server.add_media("Alpha", "video", subs={"ru.srt": SRT.encode(), "ru.srt.bak": b"x"})
    d = server.media_dir(a)
    b = server.add_media("Beta", "video", into=d); c = server.add_media("Alph", "video", into=d)
    assert play(server, b)["subs"] == [] and play(server, c)["subs"] == [] and len(play(server, a)["subs"]) == 1


def test_dots_in_video_name(server):
    i = server.add_media("Лекция 1.5", "video", subs={"ru.srt": SRT.encode()})
    assert [s["lang"] for s in play(server, i)["subs"]] == ["ru"]


@pytest.mark.parametrize("n", [1, 7, 99999])
def test_n_out_of_range_404(server, n):
    i = server.add_media("a", "video", subs={"ru.srt": SRT.encode()}); assert server.get(f"/sub/{i}/{n}.vtt")[0] == 404


def test_unknown_item_and_traversal_404(server):
    i = server.add_media("a", "video", subs={"ru.srt": SRT.encode()})
    for u in ("/sub/999999/0.vtt", f"/sub/{i}/../../app.py", f"/sub/{i}/0.srt", f"/sub/{i}/-1.vtt"):
        assert server.get(u)[0] == 404


def test_file_over_5mb_not_served(server):
    i = server.add_media("a", "video", subs={"ru.srt": b"1\n00:00:01,000 --> 00:00:02,000\n" + b"x" * (5 * 1024 * 1024 + 1)})
    assert server.get(f"/sub/{i}/0.vtt")[0] == 404


def test_symlink_out_of_folder_not_served(server, tmp_path):
    secret = tmp_path / "secret.srt"; secret.write_text(SRT, "utf-8")
    i = server.add_media("a", "video"); link = server.media_dir(i) / "a.ru.srt"
    try: link.symlink_to(secret)
    except OSError: pytest.skip("symlinks not permitted")
    assert play(server, i)["subs"] == [] and server.get(f"/sub/{i}/0.vtt")[0] == 404
