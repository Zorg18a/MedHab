# Замена старых версий новой прямо в каталоге (папка update не нужна) и поиск скачанной игры по названию карточки.
import sys, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gameupdate as gu, gamesweep as gs


def put(base, rel, data=b"x"):
    p = Path(base) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p


def lib(tmp_path):
    """Старая версия лежит в new5 (с сохранением и русским переводом), новая — в new8: так и бывает после скачивания."""
    root = tmp_path / "PG"
    put(root, "new5/Hail Dicktator v0.97.1/game/saves/1-1-LT1.save", b"OLD")
    put(root, "new5/Hail Dicktator v0.97.1/game/tl/russian/script.rpy", b"RU")
    put(root, "new5/Hail Dicktator v0.97.1/game/script.rpy", b"v1")
    return root


def plan_of(root):
    gr = next(g for g in gs.build_groups(gs.scan_library(str(root))) if g["key"] == "haildicktator")
    return gu.plan(gr)


def test_plan_sees_old_version_saves_and_translation(tmp_path):
    root = lib(tmp_path); put(root, "new8/Hail Dicktator v0.98.1/game/script.rpy", b"v2")
    pl = plan_of(root)
    assert pl["can"] and pl["keeper"]["version"] == "v0.98.1" and len(pl["olds"]) == 1
    assert pl["olds"][0]["saves"] == 1 and pl["olds"][0]["tl"] and not pl["tl_in_keeper"]


def test_replace_carries_saves_and_translation_and_trashes_old(tmp_path):
    root = lib(tmp_path); keep = put(root, "new8/Hail Dicktator v0.98.1/game/script.rpy", b"v2").parent.parent
    pl = plan_of(root); r = gu.replace(pl["keeper"]["path"], [o["path"] for o in pl["olds"]], str(root))
    assert r["ok"] and r["saves"] == 1 and r["tl"] == 1 and r["trashed"] == 1 and Path(r["dest"]) == keep   # новая остаётся на своём месте
    assert (keep / "game/saves/1-1-LT1.save").read_bytes() == b"OLD"
    assert (keep / "game/tl/russian/script.rpy").read_bytes() == b"RU"
    assert (keep / "game/script.rpy").read_bytes() == b"v2"                     # файлы новой версии не затёрты
    assert not (root / "new5/Hail Dicktator v0.97.1").exists()
    assert any((root / "_GameSweep_Trash").rglob("Hail Dicktator v0.97.1"))      # восстановимо


def test_translation_already_in_new_version_is_kept(tmp_path):
    root = lib(tmp_path); keep = root / "new8" / "Hail Dicktator v0.98.1"
    put(keep, "game/tl/russian/script.rpy", b"NEWRU"); put(keep, "game/script.rpy", b"v2")
    pl = plan_of(root); assert pl["tl_in_keeper"]
    r = gu.replace(pl["keeper"]["path"], [o["path"] for o in pl["olds"]], str(root))
    assert r["tl"] == 0 and (keep / "game/tl/russian/script.rpy").read_bytes() == b"NEWRU"


def test_same_version_copy_made_today_is_not_removed_automatically(tmp_path):
    # две копии одной версии без явной разницы по дате: решать вам («Версии и чистка»), автоматически не трогаем
    root = lib(tmp_path); put(root, "new8/Hail Dicktator v0.97.1/game/script.rpy", b"copy")
    pl = plan_of(root); assert not pl["olds"] and not pl["can"]


def test_zip_version_is_unpacked_next_to_itself(tmp_path):
    root = lib(tmp_path)
    with zipfile.ZipFile(root / "new8_x.zip", "w") as z: z.writestr("a", "b")
    (root / "new8").mkdir(); (root / "new8_x.zip").unlink()
    with zipfile.ZipFile(root / "new8/Hail Dicktator v0.98.1.zip", "w") as z: z.writestr("Hail Dicktator v0.98.1/game/script.rpy", "v2")
    pl = plan_of(root); assert pl["keeper"]["type"] == "archive" and pl["can"]
    r = gu.replace(pl["keeper"]["path"], [o["path"] for o in pl["olds"]], str(root))
    assert r["ok"] and r["saves"] == 1 and Path(r["dest"]).is_dir() and not (root / "new8/Hail Dicktator v0.98.1.zip").exists()


def test_rar_needs_manual_unpack_and_paths_are_checked(tmp_path):
    root = lib(tmp_path); (root / "new8").mkdir(); (root / "new8/Hail Dicktator v0.98.1.rar").write_bytes(b"Rar!")
    pl = plan_of(root); assert not pl["can"] and "RAR" in pl["why"]
    outside = tmp_path / "elsewhere" / "Hail Dicktator v9"; outside.mkdir(parents=True)
    assert not gu.replace(str(outside), [str(root / "new5/Hail Dicktator v0.97.1")], str(root))["ok"]
    assert (root / "new5/Hail Dicktator v0.97.1").exists()


def test_zip_slip_is_rejected(tmp_path):
    root = lib(tmp_path); (root / "new8").mkdir()
    with zipfile.ZipFile(root / "new8/Hail Dicktator v0.98.1.zip", "w") as z: z.writestr("../../evil.txt", "x")
    r = gu.replace(str(root / "new8/Hail Dicktator v0.98.1.zip"), [str(root / "new5/Hail Dicktator v0.97.1")], str(root))
    assert not r["ok"] and (root / "new5/Hail Dicktator v0.97.1").exists() and not (tmp_path / "evil.txt").exists()


def test_hidden_badge_is_found_by_card_title(tmp_path):
    # карточка «Hidden Badge», а папка HiddenBadge_20260828c в new7: раньше дата сборки прилипала к названию и пара не находилась
    root = tmp_path / "PG"; put(root, "new7/HiddenBadge_20260828c/game/a.rpy"); put(root, "new7/Other Game v1.0/game/a.rpy")
    games = gs.list_games(str(root), "auto"); assert {g["name"] for g in games} == {"HiddenBadge_20260828c", "Other Game v1.0"}
    c = gu.candidates("Hidden Badge", games)
    assert c and c[0]["name"] == "HiddenBadge_20260828c" and c[0]["score"] >= 0.9 and c[0]["version"] == "20260828c"
    assert gu.candidates("Hidden Badge: Chapter 1", games)[0]["name"] == "HiddenBadge_20260828c"   # название темы длиннее папки
    assert not [x for x in gu.candidates("Hidden Badge", games) if x["name"].startswith("Other")]
