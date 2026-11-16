# MediaHub: плеер, читалка 2.0, «Продолжить». План реализации (этап 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Дополнительно: superpowers:test-driven-development на каждой задаче.

**Goal:** Добавить страницу плеера `/p/<id>` (видео и аудио, субтитры, возобновление, горячие клавиши), читалку 2.0 (клавиши глав, режимы вписывания, масштаб) и блок «Продолжить» в Библиотеке, не нарушая WCAG 2.1 AA и 175 прежних тестов.

**Architecture:** Сначала сервер: таблица `playpos`, `GET /api/play/<id>`, субтитры `/sub/<id>/<n>.vtt`, запись позиции, `GET /api/continue`. Затем две новые страницы на ES-модулях (`player.html` + `js/player/*`, `reader.html` + `js/reader/*`), затем модуль `js/views/continue.js` в Библиотеке, затем сквозные проверки. Страницы плеера и читалки не используют центр уведомлений (его DOM есть только в `index.html`): все сообщения идут через `announce()` и область `role="alert"`.

**Tech Stack:** Python 3 (`http.server`, уже есть), ES-модули без сборки, pytest и Playwright (sync API, Chromium). Тестовые медиа: WAV из модуля `wave`; картинки страниц манги — PNG из `zlib`+`struct` (см. «Допущения», п. 5). ffmpeg и Pillow не нужны.

**Spec:** `docs/superpowers/specs/2026-11-10-mediahub-player-reader-design.md` (в архиве лежит как `2026-11-10-mediahub-player-reader-design.md`; при выполнении перенести в `specs/`).

**Baseline:** этап 1 завершён: 175 passed, 5 skipped (все axe: нет `tests/vendor/axe.min.js`), ручной чек-лист NVDA этапа 1 не подписан. В среде, где писался план, нет `pytest`; как в `ledger-stage1.md`, запуск идёт через временный shim вне проекта, а на машине автора через настоящий `pytest`.

## Global Constraints

- WCAG 2.1 AA: контраст текста ≥ 4.5:1, границ ≥ 3:1, цели ≥ 44×44 px при `targets=large`, 320 CSS px без горизонтальной прокрутки документа (кроме «Исходный размер», где прокручивается сам контейнер).
- Правила стиля: русский интерфейс (`lang="ru"`); **без inline-обработчиков** (`onclick=` и т. п. ни в HTML, ни в строках шаблонов), только `addEventListener` и делегирование по `data-action`; **шрифты в `rem`**; **цвета только токенами** из `css/tokens.css` (`var(--…)`, без hex в `player.css`); сообщения только через `announce()` / `notify()` (на страницах плеера и читалки только `announce()`).
- Без сборки и без сетевых запросов в рантайме; `start.bat`, протокол расширения и существующие таблицы не меняются (кроме защищённого `alter table progress`).
- Проверки Host, Origin и `X-MH` действуют для всех новых маршрутов (они уже в `do_GET` / `do_POST`, новые маршруты обязаны жить внутри `get()` / `post()`).
- Горячие клавиши читаются из `mh.prefs.keys` на **каждое** нажатие; не срабатывают в полях ввода, при Ctrl/Alt/Meta и при открытом `<dialog>`; пробел, PageUp/PageDown и прокрутка не перехватываются.
- Порядок: сервер → плеер → читалка → «Продолжить» → сквозные проверки. **После каждой задачи запускается весь набор** (`python -m pytest tests -q`), допустимы только пропуски axe.

### Уроки этапа 1 (из `ledger-stage1.md`), обязательные для всех задач

1. **Общая БД между тестами.** Сервер сессионный, строки копятся. `Server.reset()` чистит `items`, `progress`, `playpos`; запуск reset автоматический для любого теста, который берёт `server` (autouse-фикстура в Task 0), а не только для `page`. Тесты не опираются на порядок и не считают строки, которых не создавали сами.
2. **Классы `.sr` / `.vh`.** Скрытый от глаз текст это `.vh`; `.sr` в проекте уже занят строкой настроек и **не используется**. Перед каждым новым именем класса: `grep -n "\.имя" css/*.css reader.html`. Новые классы в `player.css` с префиксом `pl-`, в читалке `rd-`. Каждая новая страница получает проверку «отрисовано» (элементы видимы, имеют ненулевой размер) и взгляд на скриншот в тёмной и светлой теме: DOM-тесты не видят невидимое.
3. **Playwright не принимает builtin-методы как колбэки.** Только `lambda`: `page.on("pageerror", lambda e: errors.append(e))`, `page.route("**/x", lambda r: r.fulfill(...))`. Не `errors.append`.
4. **Ссылка-якорь ломает хеш-роутинг** в `index.html`. В блоке «Продолжить» нет `<a href="#…">`; действия это `<button data-action>`, переходы это ссылки на пути (`/p/<id>`, `/m/<id>`). Пропуск к содержимому на новых страницах это `<button>`, фокусирующий `<main>`.
5. **Заглушки повторяют реальную форму API.** Форма `/api/manga/<id>` берётся из `manga_info()` (`title, chapters[{id,label,files,expected,done}], total, have, progress{cid,page}`), а не из памяти.
6. **Дубли озвучивания.** Один источник речи на действие: если у элемента есть `aria-live`, то поверх него не вызывается `announce()` с тем же текстом (в Task 8 решено через скрытый префикс внутри живой области).
7. Движок `file()` отдаёт `Range` (206): медиа перематывается; новые маршруты тип `Content-Type` ставят явно.

## Допущения и вопросы к спецификации

Спецификация молчит или противоречит себе в местах ниже. По умолчанию принимаю указанное; если не согласны, скажите до начала выполнения, иначе в журнале это будет `Ruling:`.

1. **Позиция < 5 с не сохраняется, значит после «С начала» и ухода в первые секунды в БД остаётся старая позиция** и следующее открытие снова возобновит с неё. По умолчанию кнопка «С начала» дополнительно вызывает `POST /api/play/forget` (маршрут уже есть в спецификации). Альтернатива: оставить строго по тексту.
2. **`forget` для манги стирает и сохранённую страницу читалки** (так сказано в §4). Подпись кнопки «Убрать из «Продолжить»» этого не говорит. По умолчанию как в спецификации.
3. **Увеличение выше колонки.** «По ширине» при 200 % даёт страницу шире экрана на 320 px, а спецификация требует отсутствия горизонтальной прокрутки. По умолчанию: `#v{overflow-x:auto}` во всех режимах (прокручивается контейнер, не документ); тест 320 px проверяется при 100 %.
4. **Встроенный скрипт `reader.html` содержит `onclick="open_(cur+1)"` в строках шаблонов.** В модуле `open_` не глобальна, да и правило стиля запрещает inline-обработчики. Поэтому «переезд без изменения логики» включает замену этих двух мест на `data-action="next"` (логика та же).
5. **Данные манги в тестах** не через `page.route`, а через фикстуру `server.add_manga(...)` с настоящим `manifest.json` и PNG из стандартной библиотеки: так проверяются реальные `/api/manga/<id>` и `/mi/...`. `page.route` остаётся для сбойных случаев.
6. **Мелочи (в журнал как Ruling, если не возразите):** `c` без дорожек озвучивает «Субтитров нет»; `f` при выходе озвучивает «Обычный размер»; подпись без языка «Субтитры»; для материала без `dur` подпись «Продолжить» это «остановлено на 12:34»; карточка в «Продолжить» называется «Продолжить: <название>» (а не «Открыть: …», чтобы не дублировать имя ссылки из сетки); после «С начала» и после удаления карточки фокус не теряется (на медиа / на следующую карточку, а если карточек не осталось, на `h1` Библиотеки); существование файла материала в «Продолжить» не проверяется; на страницах плеера и читалки есть кнопка-пропуск как на `index.html`; на смену режима/масштаба читалка возвращается к текущей странице.

## Review Focus

1. **Конверсия SRT.** Запятая меняется только в строках таймкодов; запятые в репликах («Привет, мир») остаются. Файлы cp1251 и UTF-8 с BOM. Файл без `WEBVTT` для `.vtt`. Ссылки-симлинки за пределы папки (Task 2).
2. **Число из JSON.** `NaN`, `Infinity`, отрицательные и нечисловые `pos`/`dur` не попадают в БД и не ломают сервер (Task 1).
3. **Двойная обработка клавиш.** Chromium сам понимает часть букв (`k`, `m`, `f`) при фокусе на `<video controls>`: наш обработчик обязан вызывать `preventDefault()`, иначе пауза включится и тут же выключится (Task 6); пробел и стрелки остаются нативными.
4. **Фокус после исчезновения элемента:** кнопка «С начала», карточка «Продолжить», последняя карточка (Task 5, 10).
5. **Замена `open` только для video/audio:** остальные виды не меняются (Task 4, тест на все виды).
6. **Перенос скрипта читалки не меняет поведение:** характеризационные тесты на сохранение страницы, возобновление и не скачанную главу идут *до* переноса (Task 7).
7. **Сохранение позиции при закрытии вкладки** не гарантировано: проверяется `keepalive:true` и `X-MH`, а не сам факт доставки.
8. **Заголовки и озвучивание в живых областях без дублей** (урок 6).

---

### Task 0: Тестовая обвязка этапа 2

**Files:**
- Create: `tests/media.py`, `tests/test_harness2.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces (`tests/media.py`): `write_wav(path: Path, seconds: float = 2, rate: int = 8000) -> Path` (моно, 8 бит, тишина, модуль `wave`); `write_png(path: Path, w: int, h: int) -> Path` (`zlib`+`struct`).
- Produces (`conftest.py`, класс `Server`):
  - `add_media(title: str, kind: str = "audio", seconds: float = 2, ext: str = ".wav", raw: bytes | None = None, subs: dict[str, bytes] | None = None, thumb: bool = False) -> int` кладёт файл `<tmp>/media/<n>/<title-safe><ext>` (WAV или `raw`), рядом файлы субтитров `<stem>.<ключ словаря>` (например `{"ru.srt": b"..."}`), вставляет строку `items` с `root=''` (как у реальных видео: `/api/delete` использует папку файла) и уникальным `url`;
  - `add_manga(title: str, chapters: int = 3, pages: int = 2, missing: tuple[int, ...] = (), progress: tuple[int, int] | None = None, updated: float | None = None, manifest: bool = True) -> int` отдельный `root` на тайтл, `manifest.json` в форме `manga_info`, `chapters/<cid>/001.png…` (800×1200), `url="manga:<slug>"`, строка `progress(slug,cid,page,updated)`;
  - `set_pos(item_id: int, pos: float, dur: float, updated: float | None = None) -> None` (прямая запись в `playpos`, для проверок без браузера);
  - `get(path: str, headers: dict | None = None) -> tuple[int, dict, bytes]`, `post(path: str, body: dict | str, headers: dict | None = None) -> tuple[int, dict, bytes]` (по умолчанию с `X-MH: 1`; `str` отправляется как есть, чтобы послать `NaN`).
  - `reset()` дополнительно чистит `playpos` (если таблица есть);
  - служебные: `media_dir(item_id: int) -> Path` (папка файла материала), `_playpos_rows(item_id: int) -> int` (прямой `select count(*)`).
- Produces: autouse-фикстура `_fresh_db(request)`: если в `request.fixturenames` есть `server`, вызывает `server.reset()`; `browser` запускается с `args=["--autoplay-policy=no-user-gesture-required"]`; `open_player(page, server, item_id) -> None` (goto `/p/<id>` и ожидание `#m` с `readyState >= 1`).

- [ ] **Step 1: Прогнать базовую линию** `python -m pytest tests -q`. Ожидается 175 passed, 5 skipped (axe). Записать в ledger. Если число другое, остановиться и разобраться до любых правок.
- [ ] **Step 2: Написать тесты** (`tests/test_harness2.py`)

```python
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
    assert json.loads(server.get(f"/api/manga/{a}")[2])["title"] == "А" and json.loads(server.get(f"/api/manga/{b}")[2])["title"] == "Б"
```

- [ ] **Step 3: Запустить `python -m pytest tests/test_harness2.py -v`**. Ожидается FAIL (нет фикстур и `tests/media.py`).
- [ ] **Step 4: Реализовать** по сигнатурам. `server.get/post` на `http.client`. `add_manga` берёт форму манифеста строго из `manga_info()` (`listed`, `chapters`, `slug`, `title`); `add_item`, `reset`, остальные фикстуры этапа 1 не ломаются.
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS (175 + новые, 5 skipped).
- [ ] **Step 6: Commit** `git add -A && git commit -m "test: stage 2 harness with wav, png, manga and playpos fixtures"`

---

### Task 1: Таблица `playpos`, `/api/play`, запись позиции, `forget`

**Files:**
- Modify: `app.py` (рядом со строкой создания `progress`: таблица; в `get()`: `/api/play/<id>`; в `post()`: `/api/play/pos`, `/api/play/forget`; в `/api/delete`: чистка)
- Test: `tests/test_play_api.py`

**Interfaces:**
- Produces (app.py): `PLAY_KINDS = ('video', 'audio')`; `finished(pos: float, dur: float) -> bool` (`dur > 0 and pos >= dur - 10`); `save_pos(i: int, pos: float, dur: float) -> bool` (False, если `pos < 5`; значения валидируются `math.isfinite`, `pos >= 0`, `dur >= 0`); `play_state(i: int) -> dict | None` (`{id, title, kind, src, cover, pos, dur, finished, subs}`; `subs = []` до Task 2; None, если материала нет или вид не из `PLAY_KINDS`).
- Routes: `GET /api/play/<id>` (404 с `{'error': 'not found'}`); `POST /api/play/pos` `{id, pos, dur}` → `{'ok': 1, 'saved': bool}`, 400 при неверных числах, 404 при неизвестном id; `POST /api/play/forget` `{id}` → `{'ok': 1}`.
- DDL: `create table if not exists playpos(item_id integer primary key, pos real not null, dur real not null default 0, updated real not null)`.

- [ ] **Step 1: Написать тесты**

```python
import json, pytest

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
    i = server.add_media("a", "audio"); assert json.loads(server.post("/api/play/pos", {"id": i, "pos": 4.9, "dur": 100})[2])["saved"] is False
    assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] == 0
    server.post("/api/play/pos", {"id": i, "pos": 5, "dur": 100}); assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] == 5

@pytest.mark.parametrize("pos,dur,fin", [(90, 100, True), (89.9, 100, False), (9999, 0, False), (100, 100, True)])
def test_finished_rule(server, pos, dur, fin):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": pos, "dur": dur})
    assert json.loads(server.get(f"/api/play/{i}")[2])["finished"] is fin

@pytest.mark.parametrize("body", ['{"id":%d,"pos":NaN,"dur":0}', '{"id":%d,"pos":-3,"dur":0}', '{"id":%d,"pos":"7","dur":"x"}', '{"id":%d,"pos":Infinity,"dur":1}'])
def test_bad_numbers_rejected_and_not_stored(server, body):
    i = server.add_media("a", "audio"); assert server.post("/api/play/pos", body % i)[0] == 400
    assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] == 0

def test_forget_removes_row(server):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}); server.post("/api/play/forget", {"id": i})
    assert json.loads(server.get(f"/api/play/{i}")[2])["pos"] == 0

def test_delete_removes_playpos(server):
    i = server.add_media("a", "audio"); server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}); server.post("/api/delete", {"id": i})
    assert server._playpos_rows(i) == 0          # прямой SELECT через sqlite в фикстуре

def test_new_routes_keep_host_and_xmh_checks(server):
    i = server.add_media("a", "audio")
    assert server.get(f"/api/play/{i}", {"Host": "evil.example"})[0] == 403
    assert server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}, {"X-MH": ""})[0] == 403
    assert server.post("/api/play/pos", {"id": i, "pos": 30, "dur": 100}, {"Origin": "http://evil.example"})[0] == 403

def test_reset_clears_playpos_between_tests(server):
    i = server.add_media("a", "audio"); server.set_pos(i, 30, 100); server.reset()
    assert server._playpos_rows(i) == 0
```

(`Server._playpos_rows(i) -> int` добавляется в Task 0 как служебный метод.)

- [ ] **Step 2: Запустить `python -m pytest tests/test_play_api.py -v`**. Ожидается FAIL (404 на всех маршрутах).
- [ ] **Step 3: Реализовать.** Маршруты внутри `get()` / `post()`, а не отдельным обработчиком. `save_pos` пишет `insert or replace into playpos` с `updated=time.time()`. `/api/delete` добавляет `delete from playpos where item_id=?` в том же месте, где удаляется строка `items`. `/api/play/pos` читает тело как обычно (`json.loads` принимает `NaN`, поэтому проверка `isfinite` обязательна); для `id`, не являющегося числом, 400.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: playpos table, play api, position rules, forget"`

---

### Task 2: Субтитры: `/sub/<id>/<n>.vtt` и поле `subs`

**Files:**
- Modify: `app.py` (`H.blob`, `get()`, `play_state`)
- Test: `tests/test_play_api.py` (дополнить)

**Interfaces:**
- Produces: `sub_files(path: str) -> list[tuple[str, Path]]` (пары `(lang, файл)`; папка это `Path(path).parent`; подходят `<stem>.<lang>.srt|vtt` и `<stem>.srt|vtt`, где `lang` это `[A-Za-z0-9_-]{1,12}`; сортировка по `(lang, name)`; файл должен лежать прямо в папке материала после `resolve()`, симлинк наружу отбрасывается); `sub_label(lang: str) -> str` (`ru` Русский, `en` English, пусто «Субтитры», иначе сам код); `decode_sub(data: bytes) -> str` (`utf-8-sig`, при ошибке `cp1251`); `srt_to_vtt(text: str) -> str` (убирает BOM, `\r\n` в `\n`, запятая → точка **только** в строках вида `HH:MM:SS,mmm --> HH:MM:SS,mmm`, заголовок `WEBVTT`; текст, уже начинающийся с `WEBVTT`, возвращается как есть); `H.blob(self, data: bytes, ctype: str) -> None`.
- `subs` в `/api/play`: `[{n, lang, label, url: f"/sub/{id}/{n}.vtt"}]`, где `n` это индекс из `sub_files` (тот же порядок в обоих местах).
- Route: `GET /sub/<id>/<n>.vtt` → `text/vtt; charset=utf-8`; 404 при `n` вне диапазона, неизвестном `id`, файле > 5 МБ.

- [ ] **Step 1: Написать тесты**

```python
SRT = "1\n00:00:01,500 --> 00:00:03,000\nПривет, мир\n\n2\n00:00:04,000 --> 00:00:05,250\nВторая, реплика\n"

def vtt(server, i, n=0): s, h, b = server.get(f"/sub/{i}/{n}.vtt"); return s, h, b.decode("utf-8")

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

def test_subs_listing_order_labels_and_urls(server):
    i = server.add_media("a", "video", subs={"en.srt": SRT.encode(), "ru.srt": SRT.encode(), "de.srt": SRT.encode(), "srt": SRT.encode()})
    subs = json.loads(server.get(f"/api/play/{i}")[2])["subs"]
    assert [(s["lang"], s["label"]) for s in subs] == [("", "Субтитры"), ("de", "de"), ("en", "English"), ("ru", "Русский")]
    assert [s["n"] for s in subs] == [0, 1, 2, 3] and subs[2]["url"] == f"/sub/{i}/2.vtt"

def test_neighbour_videos_do_not_share_subs(server):
    a = server.add_media("Alpha", "video", subs={"ru.srt": SRT.encode()}); b = server.add_media("Beta", "video")
    assert json.loads(server.get(f"/api/play/{b}")[2])["subs"] == [] and len(json.loads(server.get(f"/api/play/{a}")[2])["subs"]) == 1

def test_dots_in_video_name(server):
    i = server.add_media("Лекция 1.5", "video", subs={"ru.srt": SRT.encode()})
    assert [s["lang"] for s in json.loads(server.get(f"/api/play/{i}")[2])["subs"]] == ["ru"]

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
    i = server.add_media("a", "video")
    link = server.media_dir(i) / "a.ru.srt"
    try: link.symlink_to(secret)
    except OSError: pytest.skip("symlinks not permitted")
    assert json.loads(server.get(f"/api/play/{i}")[2])["subs"] == [] and server.get(f"/sub/{i}/0.vtt")[0] == 404
```

(`Server.media_dir(i) -> Path` служебный метод из Task 0.)

- [ ] **Step 2: Запустить `python -m pytest tests/test_play_api.py -v`**. Ожидается FAIL на новых тестах.
- [ ] **Step 3: Реализовать** по сигнатурам. Регулярка маршрута `r'/sub/(\d+)/(\d+)\.vtt$'`; `n` это только индекс, имя файла из URL не используется. Проверка размера по `stat()` до чтения. Конвейер скачивания не трогается.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: subtitles as webvtt with srt conversion and safe lookup"`

---

### Task 3: `GET /api/continue`, `progress.updated`, `forget` для манги

**Files:**
- Modify: `app.py` (защищённый `alter table progress add column updated real`; `/api/progress` пишет `updated`; `get()`: `/api/continue`; `forget` для манги)
- Test: `tests/test_continue_api.py`

**Interfaces:**
- Produces: `rest_label(left: float) -> str` (`ceil(left/60)` → «осталось 12 мин»; от часа «осталось 1 ч 5 мин»; меньше минуты «осталось меньше минуты»); `continue_items(limit: int = 6) -> list[dict]` (`{id, kind, title, cover, open, pos, dur, pct, label}`).
- Правила: видео/аудио: строки `playpos` с `pos >= 5` и не `finished`, `open='/p/<id>'`, `pct=round(100*pos/dur)` (0 при `dur=0`), `label=rest_label(dur-pos)`, а при `dur=0` «остановлено на M:SS». Манга: материал виден, только если читается `manifest.json`; `progress` связывается по `slug = items.url[6:]`; `label = "<название главы из манифеста, первая буква строчная>, стр. <page+1>"`; `pct = round(100 * (номер главы среди скачанных, с 1) / (число скачанных))`; `pos = page`, `dur = 0`. Порядок по `updated` по убыванию, `null` считается 0; не более 6.

- [ ] **Step 1: Написать тесты** (до 8 материалов для лимита; `set_pos(..., updated=)` задаёт порядок)

```python
def cont(server): return json.loads(server.get("/api/continue")[2])

def test_video_item_fields_and_label(server):
    i = server.add_media("Лекция", "video"); server.set_pos(i, 2880, 3600)
    [d] = cont(server)
    assert d["id"] == i and d["kind"] == "video" and d["open"] == f"/p/{i}" and d["pct"] == 80 and d["label"] == "осталось 12 мин" and d["title"] == "Лекция"

def test_finished_and_under_5s_excluded(server):
    a, b = server.add_media("a", "audio"), server.add_media("b", "audio"); server.set_pos(a, 95, 100); server.set_pos(b, 4, 100)
    assert cont(server) == []

def test_order_fresh_first_and_limit_6(server):
    ids = [server.add_media(f"m{k}", "audio") for k in range(8)]
    for k, i in enumerate(ids): server.set_pos(i, 20, 1000, updated=1000 + k)
    got = [d["id"] for d in cont(server)]
    assert got == ids[::-1][:6]

def test_manga_label_pct_open_and_hidden_without_manifest(server):
    m = server.add_manga("Манга", chapters=4, pages=20, progress=(2, 13)); bad = server.add_manga("Без манифеста", manifest=False, progress=(0, 1))
    d = [x for x in cont(server) if x["id"] == m][0]
    assert d["open"] == f"/m/{m}" and d["label"].endswith(", стр. 14") and d["pct"] == 75 and bad not in [x["id"] for x in cont(server)]

def test_progress_without_updated_is_oldest(server):
    v = server.add_media("v", "audio"); server.set_pos(v, 30, 100, updated=5); m = server.add_manga("М", progress=(0, 0), updated=None)
    assert [d["id"] for d in cont(server)][-1] == m

def test_progress_post_sets_updated_so_manga_rises(server):
    v = server.add_media("v", "audio"); server.set_pos(v, 30, 100); m = server.add_manga("М", chapters=2)
    cid = json.loads(server.get(f"/api/manga/{m}")[2])["chapters"][0]["id"]; server.post("/api/progress", {"id": m, "cid": cid, "page": 1})
    assert cont(server)[0]["id"] == m

def test_forget_manga_removes_progress_row(server):
    m = server.add_manga("М", progress=(0, 3)); server.post("/api/play/forget", {"id": m})
    assert m not in [d["id"] for d in cont(server)] and json.loads(server.get(f"/api/manga/{m}")[2])["progress"] is None

def test_continue_keeps_host_check(server): assert server.get("/api/continue", {"Host": "evil.example"})[0] == 403
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_continue_api.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать.** `/api/progress` меняется ровно в одной строке SQL (добавить `updated`); `forget` для вида `manga` дополнительно `delete from progress where slug=?`. Таблица `progress` без столбца в старых БД получает его при старте.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: continue api with manga progress and updated column"`

---

### Task 4: Страница `/p/<id>`: каркас, вход из Библиотеки, ошибки

**Files:**
- Create: `player.html`, `css/player.css`, `css/a11y.css` (сюда переезжают без изменения правил `.vh` и `.skip`/`.skip:focus` из `css/base.css`; подключается в `index.html`, `player.html`, `reader.html`), `js/player/player.js`, `tests/test_player.py`, `tests/test_style_rules.py`
- Modify: `app.py` (`/p/(\d+)$` → `player.html`; `open` для video/audio → `/p/<id>`, одна строка в `/api/library`), `css/base.css`, `index.html`

**Interfaces:**
- Produces (`player.js`): `fmtTime(sec: number): string` (`74` → `1:14`, `754` → `12:34`, `3723` → `1:02:03`; `NaN` и отрицательные → `0:00`); `trackHtml(subs: Sub[]): string` (`<track kind="subtitles" src label [srclang]>`, без `default`, значения экранированы); `initPlayer(): Promise<void>`.
- Разметка `player.html`: ранний скрипт `mh.prefs` (копия из `reader.html`), `/css/tokens.css`, `/css/a11y.css`, `/css/player.css`; кнопка-пропуск `.skip`; `<header>`: ссылка «Библиотека» (`href="/"`), `h1#t`, `button#restart[hidden]` «С начала»; `<main id="main" tabindex="-1">`: `<div id="stage">`, `<div id="err" role="alert">`; `<dialog id="helpDlg" aria-labelledby="helpH">`; живые области `#mh-live-polite` / `#mh-live-assertive` (как в `index.html`).

- [ ] **Step 1: Написать тесты**

```python
def test_player_page_title_h1_and_video_element(server, page):
    i = server.add_media("Лекция <1>", "video"); errors = []; page.on("pageerror", lambda e: errors.append(e)); open_player(page, server, i)
    assert page.title() == "Лекция <1> — MediaHub" and page.locator("h1").inner_text() == "Лекция <1>"
    assert page.evaluate("m.tagName") == "VIDEO" and page.evaluate("m.controls && m.preload") == "metadata" and not errors

def test_no_autoplay(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    assert page.evaluate("m.paused && !m.autoplay")

def test_audio_uses_audio_element_and_decorative_cover(server, page):
    i = server.add_media("Песня", "audio", thumb=True); open_player(page, server, i)
    assert page.evaluate("m.tagName") == "AUDIO" and page.locator("main img").get_attribute("alt") == ""

def test_tracks_from_subs_none_default(server, page):
    i = server.add_media("a", "video", subs={"ru.srt": SRT, "en.srt": SRT}); open_player(page, server, i)
    t = page.evaluate("[...m.querySelectorAll('track')].map(t => [t.kind, t.label, t.default, t.getAttribute('src')])")
    assert t == [["subtitles", "English", False, f"/sub/{i}/0.vtt"], ["subtitles", "Русский", False, f"/sub/{i}/1.vtt"]]

def test_missing_item_shows_alert(server, page):
    page.goto(server.url + "/p/999999")
    assert "Материал не найден" in page.get_by_role("alert").inner_text()

def test_broken_file_shows_message_and_direct_link(server, page):
    i = server.add_media("Битый", "video", ext=".mp4", raw=b"not a video"); page.goto(f"{server.url}/p/{i}")
    page.wait_for_function("document.getElementById('err').textContent.trim() !== ''")
    assert "Не удалось воспроизвести файл" in page.get_by_role("alert").inner_text()
    assert page.get_by_role("link", name="Открыть файл напрямую").get_attribute("href") == f"/f/{i}"

def test_skip_button_first_tab_stop_and_back_link(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i); page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Перейти к содержимому"
    page.keyboard.press("Enter"); assert page.evaluate("document.activeElement.id") == "main"
    assert page.get_by_role("link", name="Библиотека").get_attribute("href") == "/"

def test_page_is_actually_rendered(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    assert page.evaluate("(() => { const r = m.getBoundingClientRect(); return r.width > 100 && r.height > 20 })()")
    assert page.evaluate("getComputedStyle(document.querySelector('.vh')).position") == "absolute"

def test_library_open_changes_only_for_video_and_audio(server):
    v, a = server.add_media("v", "video"), server.add_media("a", "audio")
    m, s, g, l = (server.add_item(t, k) for t, k in (("m", "manga"), ("s", "site"), ("g", "game"), ("l", "link")))
    got = {x["id"]: x["open"] for x in json.loads(server.get("/api/library")[2])}
    assert got[v] == f"/p/{v}" and got[a] == f"/p/{a}" and got[m] == f"/m/{m}" and got[s].startswith(f"/s/{s}/") and not got[g].startswith("/p/") and not got[l].startswith("/p/")
```

`tests/test_style_rules.py` (параметризован списком файлов этапа 2; следующие задачи дописывают свои файлы в тот же список):

```python
FILES = ["player.html", "css/player.css", "js/player/player.js"]
@pytest.mark.parametrize("f", FILES)
def test_no_inline_handlers(f): assert not re.search(r"\son(click|change|input|keydown|load|error)\s*=", (ROOT / f).read_text("utf-8"))
@pytest.mark.parametrize("f", [x for x in FILES if x.endswith((".css", ".html"))])
def test_no_px_font_sizes(f): assert not re.search(r"font-size\s*:\s*[\d.]+px", (ROOT / f).read_text("utf-8"))
def test_player_css_uses_tokens_only(): assert not re.search(r"#[0-9a-fA-F]{3,8}\b", (ROOT / "css/player.css").read_text("utf-8"))
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_player.py tests/test_style_rules.py -v`**. Ожидается FAIL (404 на `/p/<id>`, нет файлов).
- [ ] **Step 3: Реализовать.** `grep -n "\.pl-\|\.skip\|\.vh" css/*.css` перед выбором имён. Перенос `.vh`/`.skip` в `a11y.css` без правки правил; `index.html` подключает файл раньше `base.css`. `player.js` берёт `id` из `location.pathname.split('/')[2]`, запрашивает `/api/play/<id>`; 404 → `#err` «Материал не найден» и `h1` «Материал не найден»; иначе `document.title`, `h1` через `textContent`, элемент `video` или `audio` создаётся через DOM (не `innerHTML` с названием); обложка `alt=""`; `error` у элемента → сообщение и ссылка `/f/<id>`. CSS: `video{max-width:100%}`, `audio{width:100%}`, `:focus-visible{outline:2px solid var(--focus)}`, `:root[data-targets=large]` 44 px для `a, button, select`. В `app.py` ветка `/p/` рядом с `/m/`.
- [ ] **Step 4: Посмотреть скриншот** `/p/<id>` в тёмной и светлой темах и при 320 px (урок 2), записать в ledger.
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: player page /p/<id> shell, library entry, error states"`

---

### Task 5: Плеер: возобновление, «С начала», сохранение позиции

**Files:**
- Modify: `js/player/player.js`, `player.html`, `css/player.css`
- Test: `tests/test_player.py` (дополнить)

**Interfaces:**
- Produces: `shouldResume(pos: number, finished: boolean): boolean` (`pos >= 5 && !finished`); `startSaver(media: HTMLMediaElement, id: number, send?: (body: {id: number, pos: number, dur: number}) => void): {flush(): void, stop(): void}` (интервал 5000 мс только во время воспроизведения и только если позиция сдвинулась на ≥ 1 с от последней отправленной; `flush` на `pause`, `ended`, `pagehide`; по умолчанию `send` это `fetch('/api/play/pos', {method: 'POST', keepalive: true, headers: {'X-MH': '1'}, body})` с проглатыванием ошибки).

- [ ] **Step 1: Написать тесты** (файлы по 60 с: `add_media(..., seconds=60)`)

```python
def test_resume_sets_time_announces_and_shows_restart(server, page):
    i = server.add_media("a", "audio", seconds=60); server.set_pos(i, 30, 60); open_player(page, server, i)
    assert abs(page.evaluate("m.currentTime") - 30) < 0.6 and "Продолжаю с 0:30" in page.locator("#mh-live-polite").inner_text()
    assert page.locator("#restart").is_visible()

def test_no_resume_when_finished_or_under_5s(server, page):
    a, b = server.add_media("a", "audio", seconds=60), server.add_media("b", "audio", seconds=60); server.set_pos(a, 55, 60); server.set_pos(b, 4, 60)
    for i in (a, b):
        open_player(page, server, i); assert page.evaluate("m.currentTime") < 0.5 and not page.locator("#restart").is_visible()

def test_restart_rewinds_announces_hides_and_keeps_focus(server, page):
    i = server.add_media("a", "audio", seconds=60); server.set_pos(i, 30, 60); open_player(page, server, i)
    page.locator("#restart").click()
    assert page.evaluate("m.currentTime") < 1 and "С начала" in page.locator("#mh-live-polite").inner_text()
    assert not page.locator("#restart").is_visible() and page.evaluate("document.activeElement.id") == "m"
    assert page.evaluate("fetch('/api/play/%d').then(r => r.json()).then(d => d.pos)" % i) == 0      # допущение 1: forget

def test_pause_saves_position_with_xmh(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i)
    with page.expect_request("**/api/play/pos") as r:
        page.evaluate("m.currentTime = 20; m.play().then(() => m.pause())")
    assert r.value.headers["x-mh"] == "1" and json.loads(r.value.post_data)["id"] == i

def test_interval_save_every_5s_only_when_moved_1s(server, page):
    i = server.add_media("a", "audio", seconds=60); page.clock.install(); open_player(page, server, i); sent = []
    page.on("request", lambda r: sent.append(r) if r.url.endswith("/api/play/pos") else None)
    page.evaluate("m.currentTime = 12; m.play()"); page.clock.run_for(5100); n = len(sent)
    page.evaluate("m.pause()"); assert n >= 1

def test_end_marks_finished(server, page):
    i = server.add_media("a", "audio", seconds=3); open_player(page, server, i)
    page.evaluate("m.currentTime = 2.5; m.play()"); page.wait_for_function("m.ended")
    page.wait_for_timeout(300); assert json.loads(server.get(f"/api/play/{i}")[2])["finished"] is True

def test_pagehide_uses_keepalive(server, page):
    page.add_init_script("window.__f = []; const f = window.fetch; window.fetch = (u, o) => { window.__f.push([String(u), o && o.keepalive, o && o.headers]); return f(u, o) }")
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.evaluate("m.currentTime = 25")
    page.evaluate("dispatchEvent(new Event('pagehide'))")
    last = [x for x in page.evaluate("window.__f") if x[0].endswith("/api/play/pos")][-1]
    assert last[1] is True and last[2]["X-MH"] == "1"

def test_fmt_time(server, page):
    page.goto(server.url)
    r = page.evaluate("import('/js/player/player.js').then(m => [m.fmtTime(74), m.fmtTime(754), m.fmtTime(3723), m.fmtTime(NaN), m.fmtTime(-5)])")
    assert r == ["1:14", "12:34", "1:02:03", "0:00", "0:00"]
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_player.py -v`**. Ожидается FAIL на новых тестах.
- [ ] **Step 3: Реализовать.** Возобновление на `loadedmetadata` (не ждать `canplay`); `currentTime` выставляется один раз. «С начала»: `currentTime = 0`, `announce('С начала')`, `forget`, `hidden = true`, `media.focus()`. Кнопка видна только если было возобновление.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: player resume, restart, position saving"`

---

### Task 6: Плеер: горячие клавиши, субтитры по кругу, справка

**Files:**
- Create: `js/player/keys.js`
- Modify: `js/player/player.js`, `player.html` (содержимое `#helpDlg`: таблица с `<caption>`), `css/player.css`, `js/a11y/keys.js` (экспортировать `typing` как `isTyping`; поведение не меняется)
- Test: `tests/test_player.py` (дополнить), `tests/test_style_rules.py` (+ `js/player/keys.js`)

**Interfaces:**
- Produces: `keyAction(e: {key: string, ctrlKey: boolean, altKey: boolean, metaKey: boolean}): 'toggle'|'back'|'fwd'|'slower'|'faster'|'subs'|'mute'|'full'|'help'|null`; `nextSpeed(cur: number, dir: 1 | -1): number` (шаг 0.25, границы 0.5 и 2); `nextTrack(count: number, cur: number): number` (`-1` означает «выкл», порядок выкл → 0 → … → count-1 → выкл); `initPlayerKeys(d: {media: HTMLMediaElement, enabled: () => boolean, announce: (t: string) => void, openHelp: () => void}): void`. Из `a11y/keys.js`: `isTyping(el: Element | null): boolean`.

- [ ] **Step 1: Написать тесты** (клавиши нажимаются при фокусе на `body` и на самом элементе)

```python
def say(page): return page.locator("#mh-live-polite").inner_text().strip()

def test_k_toggles_and_announces(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.keyboard.press("k")
    assert page.evaluate("!m.paused") and say(page) == "Воспроизведение"; page.keyboard.press("k"); assert page.evaluate("m.paused") and say(page) == "Пауза"

def test_k_with_focus_on_media_toggles_exactly_once(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i); page.locator("#m").focus(); page.keyboard.press("k")
    page.wait_for_timeout(200); assert page.evaluate("!m.paused")          # нативный обработчик не отменил наш

def test_space_on_focused_media_stays_native(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i); page.locator("#m").focus()
    page.evaluate("window.__dp = null; addEventListener('keydown', e => { window.__dp = e.defaultPrevented }, {once: true})")
    page.keyboard.press("Space"); page.wait_for_timeout(200)
    assert page.evaluate("window.__dp") is False and page.evaluate("!m.paused")

def test_j_l_seek_10s_and_announce(server, page):
    i = server.add_media("a", "audio", seconds=60); open_player(page, server, i); page.evaluate("m.currentTime = 30")
    page.keyboard.press("l"); assert abs(page.evaluate("m.currentTime") - 40) < 0.5 and say(page) == "Вперёд на 10 секунд, 0:40"
    page.keyboard.press("j"); page.keyboard.press("j"); assert say(page) == "Назад на 10 секунд, 0:20"
    page.evaluate("m.currentTime = 3"); page.keyboard.press("j"); assert page.evaluate("m.currentTime") == 0

def test_speed_steps_and_limits(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i)
    page.keyboard.press("]"); assert page.evaluate("m.playbackRate") == 1.25 and say(page) == "Скорость 1.25"
    for _ in range(5): page.keyboard.press("]")
    assert page.evaluate("m.playbackRate") == 2
    for _ in range(9): page.keyboard.press("[")
    assert page.evaluate("m.playbackRate") == 0.5 and say(page) == "Скорость 0.5"

def test_c_cycles_off_ru_en_off(server, page):
    i = server.add_media("a", "video", subs={"en.srt": SRT, "ru.srt": SRT}); open_player(page, server, i); seen = []
    for _ in range(3): page.keyboard.press("c"); seen.append(say(page))
    assert seen == ["Субтитры: English", "Субтитры: Русский", "Субтитры выключены"]
    page.keyboard.press("c"); page.wait_for_function("m.textTracks[0].readyState === 2") ; assert page.evaluate("m.textTracks[0].cues.length") == 2

def test_c_without_tracks(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i); page.keyboard.press("c"); assert say(page) == "Субтитров нет"

def test_m_mute(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i); page.keyboard.press("m")
    assert page.evaluate("m.muted") and say(page) == "Звук выключен"; page.keyboard.press("m"); assert say(page) == "Звук включён"

def test_f_only_for_video(server, page):
    a = server.add_media("a", "audio"); open_player(page, server, a); page.keyboard.press("f"); assert not page.evaluate("document.fullscreenElement") and "Полный экран" not in say(page)

def test_f_enters_fullscreen_for_video(server, page):
    i = server.add_media("a", "video"); open_player(page, server, i)
    if not page.evaluate("document.fullscreenEnabled"): pytest.skip("fullscreen unavailable in this browser build")
    page.keyboard.press("f"); page.wait_for_function("!!document.fullscreenElement"); assert say(page) == "Полный экран"

def test_question_mark_opens_help_with_caption_and_returns_focus(server, page):
    i = server.add_media("a", "audio"); open_player(page, server, i); page.keyboard.press("?")
    assert page.locator("#helpDlg").is_visible() and page.locator("#helpDlg caption").count() == 1
    page.keyboard.press("Escape"); assert not page.locator("#helpDlg").is_visible()

def test_keys_off_modifiers_and_typing_are_ignored(server, page):
    set_prefs(page, keys=False); i = server.add_media("a", "audio"); open_player(page, server, i); page.keyboard.press("k"); assert page.evaluate("m.paused")
    page2 = page.context.new_page(); i2 = server.add_media("b", "audio"); open_player(page2, server, i2)
    page2.keyboard.press("Control+k"); page2.keyboard.press("Alt+j"); assert page2.evaluate("m.paused")
    page2.evaluate("document.body.insertAdjacentHTML('beforeend', '<input id=zz>'); zz.focus()"); page2.keyboard.type("kml"); assert page2.evaluate("m.paused && !m.muted")

def test_keys_pure_functions(server, page):
    page.goto(server.url)
    assert page.evaluate("import('/js/player/keys.js').then(m => [m.nextSpeed(1, 1), m.nextSpeed(2, 1), m.nextSpeed(0.5, -1), m.nextTrack(2, -1), m.nextTrack(2, 1), m.nextTrack(0, -1)])") == [1.25, 2, 0.5, 0, -1, -1]
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_player.py tests/test_style_rules.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать.** `keydown` на `document`; порядок отказов: `!enabled()`, модификаторы, `isTyping(document.activeElement)`, открытый `dialog[open]`, `defaultPrevented`; для обработанных клавиш `preventDefault()`. `c`: перебор `media.textTracks`, `mode = 'showing'` у одной и `'disabled'` у остальных. `play()` возвращает промис: отказ ловится, озвучивание только после успеха. Справка открывается через `openDialog`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: player hotkeys, subtitle cycling, help dialog"`

---

### Task 7: Читалка: перенос скрипта в модуль

**Files:**
- Create: `js/reader/reader.js`, `tests/test_reader2.py`
- Modify: `reader.html` (скрипт → `<script type="module" src="/js/reader/reader.js">`; в строках шаблона `onclick="open_(cur+1)"` → `data-action="next"` с делегированием; живые области `#mh-live-polite/#mh-live-assertive`; подключить `/css/a11y.css`; кнопка-пропуск), `tests/test_style_rules.py` (+ `reader.html`, `js/reader/reader.js`)

**Interfaces:**
- Produces: `reader.js` экспортирует `initReader(): Promise<void>` и (для тестов) `state()` возвращает `{cur: number, fit?: string, zoom?: number}`; прежние функции `load`, `open_`, `save` остаются внутренними, логика без изменений. Делегирование: `document.getElementById('v').addEventListener('click', e => e.target.closest('[data-action="next"]') && open_(cur + 1))`.

- [ ] **Step 1: Написать характеризационные тесты** (первые четыре проходят и на старом коде; это страховочная сеть *до* переноса, красными будут два последних)

```python
def open_reader(page, server, i): page.goto(f"{server.url}/m/{i}"); page.wait_for_selector("#v img")

def test_loads_chapter_list_and_images(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2); open_reader(page, server, i)
    assert page.locator("#c option").count() == 3 and page.locator("#v img").count() == 2 and page.title() == "Манга"

def test_resumes_at_saved_chapter_and_page(server, page):
    i = server.add_manga("Манга", chapters=3, pages=5, progress=(1, 3)); open_reader(page, server, i)
    assert page.evaluate("+document.getElementById('c').value") == 1

def test_scroll_saves_progress_with_xmh(server, page):
    i = server.add_manga("Манга", chapters=2, pages=3); open_reader(page, server, i)
    with page.expect_request("**/api/progress") as r: page.mouse.wheel(0, 900)
    b = json.loads(r.value.post_data); assert b["id"] == i and r.value.headers["x-mh"] == "1" and "cid" in b and "page" in b

def test_not_downloaded_chapter_message(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2, missing=(1,)); open_reader(page, server, i)
    page.select_option("#c", "1"); assert "ещё не скачана" in page.locator("#v").inner_text()

def test_next_chapter_button_works_without_inline_handlers(server, page):
    i = server.add_manga("Манга", chapters=3, pages=2); open_reader(page, server, i)
    assert page.evaluate("document.querySelectorAll('[onclick]').length") == 0
    page.locator("#v").get_by_role("button", name="Следующая глава").click(); assert page.evaluate("+document.getElementById('c').value") == 1

def test_script_is_module_and_no_errors(server, page):
    errors = []; page.on("pageerror", lambda e: errors.append(e)); i = server.add_manga("Манга"); open_reader(page, server, i)
    assert page.locator("script[type=module][src='/js/reader/reader.js']").count() == 1 and page.locator("script:not([src]):not([type])").count() == 1 and not errors
```

(Один встроенный классический скрипт остаётся только ранний скрипт `mh.prefs`: тест это фиксирует.)

- [ ] **Step 2: Запустить `python -m pytest tests/test_reader2.py -v`**. Ожидается: четыре характеризационных PASS, два последних FAIL. Если красных нет, тесты не доказывают перенос: исправить тесты.
- [ ] **Step 3: Реализовать** перенос «как есть», затем замена двух inline-обработчиков. Глобальные `$`, `esc`, `id`, `M`, `cur`, `tm` становятся локальными модуля.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS (в т. ч. прежний `tests/test_reader.py`).
- [ ] **Step 5: Commit** `git add -A && git commit -m "refactor: move reader script to module, drop inline handlers"`

---

### Task 8: Читалка: `modes.js`, режимы вписывания и масштаб

**Files:**
- Create: `js/reader/modes.js`
- Modify: `js/reader/reader.js`, `reader.html` (элементы в шапке и стили в существующем `<style>`)
- Test: `tests/test_reader2.py` (дополнить), `tests/test_style_rules.py` (+ `js/reader/modes.js`)

**Interfaces:**
- Produces (`modes.js`): `FITS = ['width', 'height', 'orig']`; `clampZoom(z: number): number` (диапазон 50–200, шаг 10, нечисло → 100); `loadReaderPrefs(): {fit: string, zoom: number}` и `saveReaderPrefs(p: {fit: string, zoom: number}): void` (`localStorage['mh.reader']`, значения по умолчанию `width`/100, `try/catch` вокруг каждого обращения, неизвестный `fit` → `width`); `imageStyle(fit: string, zoom: number): Record<string, string>`; `keyAction(e: {key, ctrlKey, altKey, metaKey}, ctx: {hScroll: boolean}): 'prev'|'next'|'zoom+'|'zoom-'|'zoom0'|'fit:width'|'fit:height'|'fit:orig'|'help'|null` (используется в Task 9).
- `imageStyle`: `width` → `{'--pg-w': '<zoom>%', '--pg-h': 'auto'}`; `height` → `{'--pg-w': 'auto', '--pg-h': 'calc((100vh - var(--hdr, 0px)) * <zoom/100>)'}`; `orig` → `{'--pg-w': 'calc(var(--nw, 100) * 1px * <zoom/100>)', '--pg-h': 'auto'}`, где `--nw` ставится из `img.naturalWidth` при загрузке; `--hdr` это высота шапки (`ResizeObserver`).
- Разметка шапки: `<div role="radiogroup" aria-label="Вписывание">` из трёх `button[role=radio][aria-checked]` («По ширине», «По высоте», «Исходный размер») через `initRadios`; кнопки `aria-label="Уменьшить масштаб"` / `"Увеличить масштаб"`; `<span id="zv" aria-live="polite" aria-atomic="true"><span class="vh">Масштаб </span>120 %</span>` (один источник речи, урок 6); `#v{overflow-x:auto}`; страницы `width:var(--pg-w);height:var(--pg-h)`.

- [ ] **Step 1: Написать тесты**

```python
def js_m(page, expr): return page.evaluate(f"import('/js/reader/modes.js').then(m => {expr})")

@pytest.mark.parametrize("z,want", [(10, 50), (49, 50), (55, 60), (104, 100), (105, 110), (999, 200), (None, 100), ("abc", 100)])
def test_clamp_zoom(server, page, z, want): page.goto(server.url); assert js_m(page, f"m.clampZoom({json.dumps(z)})") == want

def test_image_style_values(server, page):
    page.goto(server.url)
    assert js_m(page, "m.imageStyle('width', 120)")["--pg-w"] == "120%" and "1.2" in js_m(page, "m.imageStyle('height', 120)")["--pg-h"] and "1.2" in js_m(page, "m.imageStyle('orig', 120)")["--pg-w"]

def test_prefs_default_roundtrip_corrupt_and_blocked(server, page):
    page.goto(server.url); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 100}
    page.evaluate("localStorage.setItem('mh.reader', '{broken')"); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 100}
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'zzz', zoom: 1000}))"); assert js_m(page, "m.loadReaderPrefs()") == {"fit": "width", "zoom": 200}
    p = page.context.new_page(); p.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})"); errors = []; p.on("pageerror", lambda e: errors.append(e))
    i = server.add_manga("М"); p.goto(f"{server.url}/m/{i}"); p.wait_for_selector("#v img"); assert not errors

def widths(page): return page.evaluate("[...document.querySelectorAll('#v img')].map(i => Math.round(i.getBoundingClientRect().width))")

def test_fit_width_orig_and_zoom_change_rendered_sizes(server, page):
    i = server.add_manga("М", pages=2); page.set_viewport_size({"width": 1200, "height": 800}); open_reader(page, server, i)
    w100 = widths(page)[0]; assert w100 <= 900
    page.get_by_role("radio", name="Исходный размер").click(); assert widths(page)[0] == 800
    page.get_by_role("button", name="Увеличить масштаб").click(); page.get_by_role("button", name="Увеличить масштаб").click(); assert widths(page)[0] == 960
    page.get_by_role("radio", name="По высоте").click(); h = page.evaluate("document.querySelector('#v img').getBoundingClientRect().height"); assert 500 < h < 800 * 1.3

def test_zoom_live_region_value_and_limits(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); b = page.get_by_role("button", name="Увеличить масштаб")
    for _ in range(12): b.click()
    assert page.locator("#zv").inner_text().replace("\n", "").strip().endswith("200 %") and page.locator("#zv").get_attribute("aria-live") == "polite"
    assert page.get_by_role("button", name="Увеличить масштаб").is_visible()

def test_radiogroup_semantics_and_arrow_keys(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); g = page.get_by_role("radiogroup", name="Вписывание")
    assert g.get_by_role("radio").count() == 3 and g.get_by_role("radio", name="По ширине").get_attribute("aria-checked") == "true"
    g.get_by_role("radio", name="По ширине").focus(); page.keyboard.press("ArrowRight"); assert g.get_by_role("radio", name="По высоте").get_attribute("aria-checked") == "true"

def test_choice_persists_in_mh_reader(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); page.get_by_role("radio", name="Исходный размер").click(); page.get_by_role("button", name="Увеличить масштаб").click()
    assert page.evaluate("JSON.parse(localStorage.getItem('mh.reader'))") == {"fit": "orig", "zoom": 110}
    page.reload(); page.wait_for_selector("#v img"); assert page.get_by_role("radio", name="Исходный размер").get_attribute("aria-checked") == "true"

def test_mode_change_keeps_current_page_in_view(server, page):
    i = server.add_manga("М", pages=6); open_reader(page, server, i); page.locator("#v img").nth(3).scroll_into_view_if_needed()
    page.get_by_role("radio", name="По высоте").click(); page.wait_for_timeout(200)
    assert page.evaluate("(() => { const r = document.querySelectorAll('#v img')[3].getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight })()")

def test_document_does_not_scroll_horizontally_at_320_and_200_percent(server, page):
    i = server.add_manga("М"); page.set_viewport_size({"width": 320, "height": 640}); open_reader(page, server, i)
    page.evaluate("localStorage.setItem('mh.reader', JSON.stringify({fit: 'width', zoom: 200}))"); page.reload(); page.wait_for_selector("#v img")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_reader2.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** по сигнатурам; `FIT` применяется как CSS-переменные на `#v` (`style.setProperty`), без inline-обработчиков; при смене режима запоминается индекс текущей страницы (как в `save()`) и после перерисовки `scrollIntoView()`. Проверить `grep -n "\.rd-\|\.sr\b" reader.html css/*.css` на коллизии.
- [ ] **Step 4: Посмотреть скриншоты** в трёх режимах, тёмная и светлая тема, 320 px (урок 2).
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: reader fit modes and zoom with persisted prefs"`

---

### Task 9: Читалка: клавиши глав и режимов, фокус на заголовке главы, справка

**Files:**
- Modify: `js/reader/reader.js`, `js/reader/modes.js` (`keyAction` из Task 8), `reader.html` (`<h2 id="ch" tabindex="-1">` над страницами, `<dialog id="helpDlg">` с `<caption>`)
- Test: `tests/test_reader2.py` (дополнить)

**Interfaces:**
- Consumes: `isTyping` (Task 6), `loadPrefs` (`mh.prefs`), `announce`, `openDialog`.
- Produces: `initReaderKeys(d: {enabled: () => boolean, prev: () => void, next: () => void, zoom: (delta: number | 0) => void, fit: (f: string) => void, openHelp: () => void, hScroll: () => boolean}): void`. Смена главы вызывает `announce('Глава N из M')` и `ch.focus({preventScroll: true})` **только по действию пользователя** (клавиша, кнопки, список), не при первой загрузке (решение этапа 1, Task 4).

- [ ] **Step 1: Написать тесты**

```python
def say(page): return page.locator("#mh-live-polite").inner_text().strip()

def test_chapter_keys_announce_and_focus_h2(server, page):
    i = server.add_manga("М", chapters=3); open_reader(page, server, i)
    page.keyboard.press("n"); assert say(page) == "Глава 2 из 3" and page.evaluate("document.activeElement.id") == "ch" and page.locator("#ch").evaluate("e => e.tagName") == "H2"
    page.keyboard.press("ArrowRight"); assert say(page) == "Глава 3 из 3"; page.keyboard.press("p"); page.keyboard.press("ArrowLeft"); assert say(page) == "Глава 1 из 3"

def test_no_focus_steal_on_first_load(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); assert page.evaluate("document.activeElement.id") != "ch"

def test_edges_do_not_wrap(server, page):
    i = server.add_manga("М", chapters=2); open_reader(page, server, i); page.keyboard.press("p"); assert page.evaluate("+document.getElementById('c').value") == 0

def test_zoom_keys_announce_through_single_live_region(server, page):
    i = server.add_manga("М"); open_reader(page, server, i)
    page.keyboard.press("+"); assert page.locator("#zv").inner_text().replace("\n", "").strip() == "Масштаб 110 %" and say(page) == ""
    page.keyboard.press("-"); page.keyboard.press("-"); assert "90 %" in page.locator("#zv").inner_text(); page.keyboard.press("0"); assert "100 %" in page.locator("#zv").inner_text()

def test_fit_keys_announce_and_sync_radios(server, page):
    i = server.add_manga("М"); open_reader(page, server, i)
    for key, name in (("h", "По высоте"), ("o", "Исходный размер"), ("w", "По ширине")):
        page.keyboard.press(key); assert say(page) == name and page.get_by_role("radio", name=name).get_attribute("aria-checked") == "true"

def test_arrows_belong_to_browser_in_orig_mode_with_hscroll_but_p_n_work(server, page):
    i = server.add_manga("М", chapters=3); page.set_viewport_size({"width": 400, "height": 700}); open_reader(page, server, i); page.keyboard.press("o")
    assert page.evaluate("document.getElementById('v').scrollWidth > document.getElementById('v').clientWidth")
    page.keyboard.press("ArrowRight"); assert page.evaluate("+document.getElementById('c').value") == 0
    page.keyboard.press("n"); assert page.evaluate("+document.getElementById('c').value") == 1

def test_arrows_work_in_orig_mode_without_hscroll(server, page):
    i = server.add_manga("М", chapters=3); page.set_viewport_size({"width": 1600, "height": 900}); open_reader(page, server, i); page.keyboard.press("o")
    assert not page.evaluate("document.getElementById('v').scrollWidth > document.getElementById('v').clientWidth"); page.keyboard.press("ArrowRight"); assert page.evaluate("+document.getElementById('c').value") == 1

def test_scroll_keys_not_intercepted(server, page):
    i = server.add_manga("М", pages=6); open_reader(page, server, i)
    page.evaluate("window.__dp = []; addEventListener('keydown', e => window.__dp.push([e.key, e.defaultPrevented]))")
    for k in ("Space", "PageDown", "PageUp", "ArrowDown"): page.keyboard.press(k)
    assert not any(d for _, d in page.evaluate("window.__dp"))

def test_keys_off_modifiers_select_and_dialog_ignored(server, page):
    i = server.add_manga("М", chapters=3); set_prefs(page, keys=False); open_reader(page, server, i); page.keyboard.press("n"); assert page.evaluate("+document.getElementById('c').value") == 0
    p = page.context.new_page(); open_reader(p, server, i); p.keyboard.press("Control+n"); p.keyboard.press("Alt+ArrowRight"); assert p.evaluate("+document.getElementById('c').value") == 0
    p.locator("#c").focus(); p.keyboard.press("n"); assert p.evaluate("+document.getElementById('c').value") == 0

def test_question_mark_opens_help_and_returns_focus(server, page):
    i = server.add_manga("М"); open_reader(page, server, i); page.keyboard.press("?"); assert page.locator("#helpDlg").is_visible() and page.locator("#helpDlg caption").count() == 1
    page.keyboard.press("Escape"); assert not page.locator("#helpDlg").is_visible()

def test_chapter_change_still_saves_progress(server, page):
    i = server.add_manga("М", chapters=2, pages=3); open_reader(page, server, i)
    page.keyboard.press("n"); page.mouse.wheel(0, 600); page.wait_for_timeout(900)
    assert json.loads(server.get(f"/api/manga/{i}")[2])["progress"] is not None
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_reader2.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать.** `hScroll()` = `#v.scrollWidth > #v.clientWidth` **и** `fit === 'orig'`. Клавиши только из `keyAction`, `preventDefault()` у обработанных. Подпись `h2` это `label` главы из манифеста. В сообщении о нескачанной главе добавить «, не скачана».
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: reader hotkeys, chapter focus and help"`

---

### Task 10: Блок «Продолжить» в Библиотеке

**Files:**
- Create: `js/views/continue.js`, `tests/test_continue.py`
- Modify: `index.html` (`<div id="cont"></div>` в `#v-library` над `#lib`), `js/views/library.js` (вызов `loadContinue()` из `loadLibrary()`, `syncContinue()` из `draw()` и при `input` в `#q`), `css/components.css`, `tests/test_style_rules.py` (+ `js/views/continue.js`), `tests/conftest.py` (`open_seeded('library')` кладёт позицию для видео «Лекция по физике»)

**Interfaces:**
- Produces: `continueHtml(items: ContinueItem[]): string` (`<section aria-labelledby="contH"><h2 id="contH" tabindex="-1">Продолжить</h2><ul>` + по `<li data-id>` на элемент: `<article class="c">`, ссылка `a.cv` на `open` с `aria-label="Продолжить: <название>"`, `h3`, `<p class="a">` с подписью, `progressHtml(pct, 'Просмотрено')`, `<button type="button" data-action="forget" data-id aria-label="Убрать из «Продолжить»: <название>">`; пустой список → `''`; всё экранируется `esc`); `loadContinue(): Promise<void>` (GET `/api/continue`, рендер в `#cont`; сбой сети не бросает); `syncContinue(show: boolean): void` (показ только при непустом списке, пустом поиске и фильтре «Все»); удаление: POST `/api/play/forget`, `announce('Убрано из «Продолжить»')`, перерисовка и перенос фокуса (на `.cv` следующей карточки, иначе на `#contH`, иначе на `h1` Библиотеки).

- [ ] **Step 1: Написать тесты**

```python
def seed(server, n=3):
    ids = [server.add_media(f"Фильм {k}", "video") for k in range(n)]
    for k, i in enumerate(ids): server.set_pos(i, 30, 600, updated=1000 + k)
    return ids[::-1]                           # порядок на странице: свежие первыми

def test_block_hidden_when_nothing_to_continue(server, page):
    server.add_media("a", "video"); page.goto(server.url); page.wait_for_selector(".cv"); assert page.locator("#contH").count() == 0

def test_block_appears_after_position_is_saved(server, page):
    i = server.add_media("a", "video", seconds=60); open_player(page, server, i)
    with page.expect_request("**/api/play/pos"): page.evaluate("m.currentTime = 20; m.play().then(() => m.pause())")
    page.goto(server.url); page.wait_for_selector("#contH"); assert page.locator("section[aria-labelledby=contH] li").count() == 1

def test_markup_progressbar_and_label(server, page):
    [i] = seed(server, 1); page.goto(server.url); s = page.locator("section[aria-labelledby=contH]")
    pb = s.get_by_role("progressbar", name="Просмотрено"); assert pb.get_attribute("aria-valuenow") == "5" and "осталось" in s.inner_text()
    assert s.get_by_role("link", name="Продолжить: Фильм 0").get_attribute("href") == f"/p/{i}" and s.locator("h3").count() == 1

def test_titles_escaped(server, page):
    i = server.add_media('"><img src=x onerror=window.__x=1> <b>Тест</b>', "video"); server.set_pos(i, 30, 600); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.evaluate("window.__x") is None and page.locator("#cont b").count() == 0

def test_hidden_while_searching_and_with_filter_and_back(server, page):
    seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    page.fill("#q", "Фильм 1"); page.wait_for_selector("#contH", state="hidden")
    page.fill("#q", ""); page.wait_for_selector("#contH")
    page.get_by_role("button", name="Видео").click(); page.wait_for_selector("#contH", state="hidden")
    page.get_by_role("button", name="Все").click(); page.wait_for_selector("#contH")

def test_remove_moves_focus_to_next_card_announces_and_forgets(server, page):
    a, b, c = seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    page.get_by_role("button", name="Убрать из «Продолжить»: Фильм 2").click()
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Продолжить: Фильм 1" and "Убрано из «Продолжить»" in page.locator("#mh-live-polite").inner_text()
    assert json.loads(server.get(f"/api/play/{a}")[2])["pos"] == 0

def test_remove_last_card_focuses_heading_and_only_card_focuses_h1(server, page):
    a, b = seed(server, 2); page.goto(server.url); page.wait_for_selector("#contH")
    page.get_by_role("button", name="Убрать из «Продолжить»: Фильм 0").click(); assert page.evaluate("document.activeElement.id") == "contH"
    page.get_by_role("button", name="Убрать из «Продолжить»: Фильм 1").click()
    page.wait_for_selector("#contH", state="detached"); assert page.evaluate("document.activeElement.tagName") == "H1"

def test_item_stays_in_library_grid_after_remove(server, page):
    seed(server, 1); page.goto(server.url); page.wait_for_selector("#contH"); page.get_by_role("button", name="Убрать из «Продолжить»: Фильм 0").click()
    assert page.get_by_role("link", name="Открыть: Фильм 0").count() == 1

def test_cards_join_j_k_navigation(server, page):
    seed(server, 2); page.goto(server.url); page.wait_for_selector("#contH"); page.keyboard.press("j")
    assert page.evaluate("document.activeElement.closest('#cont') !== null")

def test_no_anchor_hash_links_and_no_inline_handlers_in_block(server, page):
    seed(server); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.evaluate("document.querySelectorAll('#cont a[href^=\"#\"], #cont [onclick]').length") == 0

def test_manga_card_links_to_reader_with_chapter_label(server, page):
    m = server.add_manga("Манга", chapters=3, pages=20, progress=(1, 13)); page.goto(server.url); page.wait_for_selector("#contH")
    assert page.get_by_role("link", name="Продолжить: Манга").get_attribute("href") == f"/m/{m}" and "стр. 14" in page.locator("#cont").inner_text()

def test_block_is_rendered_and_fits_320(server, touch_page):
    seed(server); touch_page.set_viewport_size({"width": 320, "height": 640}); touch_page.goto(server.url); touch_page.wait_for_selector("#contH")
    assert touch_page.locator("#cont .c").first.bounding_box()["width"] > 100 and touch_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_continue.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать.** `grep -n "\.cont\|\.rd-\|\.sr\b" css/*.css` перед именами. Рендер `<ul>` без маркеров, карточки в сетке `.grid` прежнего вида. Размеры только `rem`, цвета токенами. Кнопка «Убрать» видна при фокусе и на касаниях (как `.act`).
- [ ] **Step 4: Посмотреть скриншот** Библиотеки с блоком: тёмная и светлая темы, 320 px.
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: continue block in library with forget and focus handling"`

---

### Task 11: Сквозные проверки и документация

**Files:**
- Modify: `tests/conftest.py` (`PAGES = ["player", "reader"]`, `ALL_VIEWS = VIEWS + PAGES`, `open_any(page, server, name)`: индексные разделы через `open_seeded`, плеер через `add_media(subs=…)` + `set_pos` + `open_player`, читалка через `add_manga`), `tests/test_rules.py`, `tests/test_matrix.py`, `tests/test_keyboard_walk.py`, `README.md`
- Create: `docs/a11y-manual-stage2.md`

**Interfaces:**
- Consumes: `run_axe`, `set_prefs`, `open_seeded`, `open_player` (Task 0, этап 1).

- [ ] **Step 1: Расширить параметризацию.** В трёх файлах `@pytest.mark.parametrize("view", VIEWS)` → `ALL_VIEWS`, вызов `open_seeded` → `open_any` (для страниц `/p` и `/m`: имена элементов, структура и ссылки, отсутствие `[onclick]`, контраст текста в 4 сочетаниях тема×контраст, 320 px, цели 44 px при `targets=large`, обход Tab с видимым фокусом до возврата на кнопку-пропуск; axe в матрице пропускается без `tests/vendor/axe.min.js`).
- [ ] **Step 2: Запустить `python -m pytest tests -q`**. Ожидается: падения указывают на несоответствия новых страниц (как в Task 14 этапа 1).
- [ ] **Step 3: Исправить найденное** в разметке и CSS страниц. Проверки, неприменимые к страницам плеера и читалки по смыслу (например, число `nav a`), исключаются явно, с причиной в ledger, а не молчаливым `skip`. Контроль «тест умеет падать»: временно сломать (убрать `aria-label` у `#restart`, поднять `font-size` в px) и увидеть красный; вернуть.
- [ ] **Step 4: Написать `docs/a11y-manual-stage2.md`**: 5 сценариев (возобновление видео; меню субтитров и клавиша `c`; озвучивание клавиш плеера; режимы и масштаб читалки; «Продолжить» с удалением и фокусом) × NVDA с Firefox и Яндекс Браузером; колонки «ожидаемое озвучивание» и «результат / подпись». Обновить `README.md` (страница плеера, клавиши плеера и читалки, субтитры `.srt/.vtt` рядом с файлом, «Продолжить»).
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS целиком; указать число passed и skipped (axe).
- [ ] **Step 6: Commit** `git add -A && git commit -m "test: stage 2 acceptance matrix, manual checklist, docs"`
- [ ] **Step 7: Журнал.** `docs/superpowers/ledger-stage2.md` со всеми `Ruling:`; в нём прямо отмечено: готовность этапа требует подписи ручного чек-листа; без неё этап не объявляется готовым.

---

## Покрытие критериев и требований спецификации

| Критерий / требование | Где выполняется | Задачи |
|---|---|---|
| 1.2.2 Субтитры: `<track>` из `.srt/.vtt`, `c`, меню плеера | `sub_files`, `srt_to_vtt`, `trackHtml`, `nextTrack` | 2, 4, 6 |
| 2.1.1 Клавиатура: всё доступно с клавиатуры | клавиши плеера и читалки, кнопки, radiogroup | 6, 8, 9, 11 |
| 2.1.4 Односимвольные клавиши: общий переключатель | `enabled()` на каждое нажатие, тесты `keys=False` | 6, 9 |
| 2.2.2 Пауза: нет автозапуска, `preload="metadata"` | `test_no_autoplay`, разметка | 4 |
| 2.4.2, 2.4.3: заголовок страницы, фокус на главе | `document.title`, `h2#ch` | 4, 9 |
| 1.4.4, 1.4.10: масштаб 50–200 %, 320 px | `modes.js`, `#v{overflow-x:auto}`, матрица | 8, 11 |
| 4.1.2, 4.1.3: имена, роли, состояния, озвучивание | `radiogroup`, `progressbar`, `announce`, `#zv` | 4–6, 8–10 |
| §4 Сервер: таблица, `/api/play`, `pos`, `forget`, `continue`, `sub`, чистка при удалении | `app.py` | 1, 2, 3 |
| §4 Правила позиции (< 5 с, завершено, `dur`) | `save_pos`, `finished` | 1 |
| §4 Манга в «Продолжить»; `progress.updated` | `continue_items`, `alter table` | 3 |
| §4 Вход в плеер: замена `open` только для video/audio | одна строка `/api/library` | 4 |
| §5 Плеер: разметка, возобновление, сохранение, клавиши, ошибки | `player.*` | 4, 5, 6 |
| §6 Читалка: `modes.js`, режимы, шапка, клавиши, смена главы | `reader.js`, `modes.js` | 7, 8, 9 |
| §7 «Продолжить»: разметка, удаление, фокус, `j`/`k` | `continue.js` | 10 |
| §9 Тесты: `test_play_api`, `test_player`, `test_reader2`, `test_continue`, сквозные | файлы тестов | 1–11 |
| §9 Готовность: все тесты зелёные, чек-лист подписан | `a11y-manual-stage2.md` (подпись за автором) | 11 |
| §10 Риски: mkv/avi, кодировки, потеря позиции, замена `open`, перенос скрипта | сообщение + `/f/<id>`; `cp1251`+5 МБ; `keepalive`; тест видов; характеризационные тесты | 2, 4, 5, 7 |
