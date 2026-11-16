"""Лента обновлений: «проверить источник → сравнить → событие». Здесь только сравнение, без сети и базы (их даёт app.py), поэтому всё проверяется тестами.

Событие: {kind, key, item_id, title, detail, url, action, payload}.
  key уникален для факта («игра X, источник Y, версия Z»), поэтому повторная проверка того же состояния не плодит записи.
  action: что предложить в один щелчок: open (открыть страницу), download (скачать новые главы / видео).
Первая проверка источника ничего не сообщает: она только запоминает, что уже было («базовая линия»), иначе при добавлении канала с сотней видео лента утонула бы."""
import re

import gamelib

KINDS = ("game", "manga", "video")
KIND_NAMES = {"game": "Игры", "manga": "Манга", "video": "Видео"}
MAX_NEW_VIDEOS = 10        # из одного канала за проверку
SEEN_KEEP = 300            # сколько идентификаторов видео помнить на источник


def game_event(item_id: int, title: str, site: str, site_name: str, old: str, new: str, url: str):
    """Версия в теме изменилась. Без прежней версии (первое чтение) события нет."""
    old, new = (old or "").strip(), (new or "").strip()
    if not old or not new or old == new:
        return None
    newer = gamelib.newer(new, old)
    return {"kind": "game", "key": f"game:{item_id}:{site}:{new}", "item_id": item_id, "title": title,
            "detail": f"{site_name}: {'новая версия' if newer else 'версия изменилась'} {new} (было {old})", "url": url, "action": "open",
            "payload": {"site": site, "old": old, "new": new}}


def manga_event(item_id: int, title: str, slug: str, known: set, site_chapters: list, source_url: str):
    """Главы на сайте, которых не было при последней загрузке. site_chapters: [{cid, label, url}] в порядке сайта."""
    new = [c for c in site_chapters if c["cid"] not in known]
    if not new:
        return None
    new.sort(key=lambda c: [float(x) if re.fullmatch(r"\d+(?:\.\d+)?", x) else 0.0 for x in c["cid"].split("-")])
    names = [c["label"] for c in new]
    shown = ", ".join(names[:3]) + (f" и ещё {len(names) - 3}" if len(names) > 3 else "")
    return {"kind": "manga", "key": f"manga:{slug}:{new[-1]['cid']}", "item_id": item_id, "title": title,
            "detail": f"Новых глав: {len(new)}: {shown}", "url": source_url, "action": "download",
            "payload": {"cids": [c["cid"] for c in new], "slug": slug}}


def video_events(watch_id: int, watch_title: str, entries: list, seen: list, baselined: bool):
    """Новые видео канала или плейлиста. Возвращает (события, новый список виденных, baseline_готов)."""
    ids = [str(e.get("id")) for e in entries if e and e.get("id")]
    if not baselined:
        return [], list(dict.fromkeys(ids + list(seen)))[:SEEN_KEEP], True
    known = set(seen)
    new = [e for e in entries if e and e.get("id") and str(e["id"]) not in known][:MAX_NEW_VIDEOS]
    ev = [{"kind": "video", "key": f"video:{watch_id}:{e['id']}", "item_id": None, "title": e.get("title") or str(e["id"]),
           "detail": f"Новое видео · {watch_title or 'источник'}", "url": e.get("url") or e.get("webpage_url") or "", "action": "download",
           "payload": {"watch": watch_id, "video": str(e["id"])}} for e in new if (e.get("url") or e.get("webpage_url"))]
    return ev, list(dict.fromkeys([str(e["id"]) for e in new] + ids + list(seen)))[:SEEN_KEEP], True


def due(last_checked: float, hours: float, now: float) -> bool:
    """Пора ли проверять по расписанию (0 часов — выключено)."""
    return hours > 0 and now - (last_checked or 0) >= hours * 3600
