"""Обновляет extension/sites.js и host_permissions в extension/manifest.json из sites.json.
python tools/gen_sites.py          записать
python tools/gen_sites.py --check  только проверить (код возврата 1, если файлы устарели)"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import sites as S


def expected():
    sl = S.load()
    man = json.loads((ROOT / "extension" / "manifest.json").read_text("utf-8"))
    return {"extension/sites.js": S.render_js(sl),
            "extension/manifest.json": json.dumps(S.render_manifest(man, sl), ensure_ascii=False, indent=2)}


if __name__ == "__main__":
    bad = 0
    for rel, text in expected().items():
        p = ROOT / rel
        same = p.exists() and p.read_text("utf-8") == text
        if "--check" in sys.argv:
            bad += not same; print(("ok " if same else "УСТАРЕЛ ") + rel)
        elif not same:
            p.write_text(text, "utf-8"); print("записан " + rel)
    sys.exit(1 if bad else 0)
