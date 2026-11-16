# MediaHub: основа доступности. План реализации (этап 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести UI MediaHub на ES-модули и закрыть все 22 пункта аудита WCAG 2.1 AA, добавив центр уведомлений, режимы отображения и горячие клавиши.

**Architecture:** `app.py` отдаёт `/js/*` и `/css/*` как статику. Прежний inline-скрипт переезжает в `js/legacy.js` (классический скрипт) и по одному разделу переносится в `js/views/*.js`; на каждом шаге приложение работает. Общие кирпичи (`a11y/*`, `ui/*`) подключаются к legacy через `window.MH`.

**Tech Stack:** Python 3 (`http.server`, уже есть), ES-модули без сборки, pytest и Playwright (sync API, Chromium) для тестов, `axe-core` в `tests/vendor`.

**Spec:** `docs/superpowers/specs/2026-11-08-mediahub-a11y-foundation-design.md`

## Global Constraints

- Стандарт WCAG 2.1 AA: контраст текста ≥ 4.5:1, границ и элементов интерфейса ≥ 3:1, цели ≥ 44×44 px в режиме `targets=large`, зум 200 % без горизонтальной прокрутки.
- Без сборки и без сетевых запросов в рантайме; `start.bat` не меняется.
- Размеры шрифтов в CSS только в `rem`; режимы хранятся в `localStorage` под ключом `mh.prefs`.
- Тосты живут 8 с с паузой при наведении и фокусе; журнал на 50 записей; ошибки `assertive` и не гаснут сами.
- Горячие клавиши: `g`+`l/i/d/g/s/n`, `j/k`, `/`, `?`; таймаут последовательности 1.5 с; переключатель в настройках.
- Проверки Host и Origin в `app.py` сохраняются; протокол расширения и таблицы БД не меняются; порт по умолчанию 8765.
- Тексты интерфейса на русском; `lang="ru"` сохраняется.

## Review Focus

1. Windows отдаёт `.js` как `text/plain` из реестра, и модули молча не загружаются (тест в Task 1: явный `Content-Type`).
2. `localStorage` недоступен или в `mh.prefs` испорченный JSON: приложение обязано загрузиться с настройками по умолчанию (Task 3).
3. Сервер остановлен или опрос падает посреди сессии: без необработанных исключений, постоянный статус и восстановление (Task 4, 5).
4. `g` в поле ввода, `Ctrl+G`, `Alt+←`: ничего не перехватывается (Task 7).
5. Названия с `<`, `"` и кириллицей в `aria-label`, тостах и чипах не ломают разметку (Task 9).

---

### Task 0: Тестовая обвязка и git

**Files:**
- Create: `tests/conftest.py`, `tests/requirements-dev.txt`, `tests/test_smoke.py`, `tests/vendor/axe.min.js`, `tests/vendor/VERSION`
- Modify: `app.py:1130` (порт и браузер из окружения)

**Interfaces:**
- Produces: фикстуры `server` (сессионная; `.url: str`, `.port: int`, `.add_item(title: str, kind: str) -> int` вставляет строку в `library.db` копии проекта с уникальными `url`, `path`, `root`, для `kind='game'` ещё минимальный JSON в столбец `info`), `page` (Playwright `Page`, новый контекст на тест), `touch_page` (контекст с `has_touch=True, is_mobile=True`); хелперы `open_view(page, server, view: str) -> None`, `run_axe(page) -> list[dict]` (нарушения с `impact` в `serious|critical`), `set_prefs(page, **prefs) -> None` (через `add_init_script`), `stub_inbox(page, titles: list[str]) -> None` (перехватывает `**/api/inbox` и отдаёт один ожидающий пакет с вкладками `titles`).

- [ ] **Step 1: Если каталог не git-репозиторий, выполнить `git init` и закоммитить исходное состояние** (`git add -A && git commit -m "chore: baseline"`).
- [ ] **Step 2: Написать тест**

```python
def test_index_loads_and_has_five_nav_links(page, server):
    page.goto(server.url)
    assert page.locator("nav a").count() == 5
```

- [ ] **Step 3: Запустить `python -m pytest tests/test_smoke.py -v`**. Ожидается FAIL (нет фикстур).
- [ ] **Step 4: Реализовать**
  - `app.py`: `PORT = int(os.environ.get('MEDIAHUB_PORT', 8765))`; `webbrowser.open` только если не задан `MEDIAHUB_NO_BROWSER`; сообщение и сервер используют `PORT`.
  - `conftest.py`: `server` копирует проект во временный каталог без `tests`, `ffmpeg`, `library.db`, `settings.json`, пишет `settings.json` (`folder` во временный каталог), запускает `python app.py` на свободном порту с обоими переменными окружения, ждёт ответа на `/`, по завершении убивает процесс.
  - `requirements-dev.txt`: `pytest`, `playwright`. `axe.min.js` берётся из npm-пакета `axe-core`, версия записывается в `VERSION`.
- [ ] **Step 5: Запустить тест**. Ожидается PASS (после `python -m playwright install chromium`).
- [ ] **Step 6: Commit** `git add -A && git commit -m "test: harness with server and playwright fixtures"`

---

### Task 1: Статика `/js/*` и `/css/*`

**Files:**
- Modify: `app.py:982-1025` (`H.get`)
- Create: `js/main.js` (заглушка `export {}`), `css/tokens.css` (пустой)
- Test: `tests/test_static.py`

**Interfaces:**
- Produces: `H.static(self, p: str) -> None` отдаёт файл из `BASE/js` или `BASE/css`.

- [ ] **Step 1: Написать тесты**

```python
def test_js_served_as_javascript(server, page):
    r = page.request.get(server.url + "/js/main.js")
    assert r.status == 200 and r.headers["content-type"].startswith("text/javascript")

def test_css_content_type(server, page):
    assert page.request.get(server.url + "/css/tokens.css").headers["content-type"].startswith("text/css")

def test_traversal_and_other_extensions_rejected(server, page):
    for u in ("/js/../app.py", "/js/%2e%2e/app.py", "/js/x.py", "/js/"):
        assert page.request.get(server.url + u).status in (403, 404)

def test_host_check_kept(server):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", server.port); c.request("GET", "/js/main.js", headers={"Host": "evil.example"})
    assert c.getresponse().status == 403
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_static.py -v`**. Ожидается FAIL (404).
- [ ] **Step 3: Реализовать** в `H.get` ветку `re.match(r'/(js|css)/[\w./-]+\.(js|css)$', p)` перед финальным 404; `static` резолвит путь, требует, чтобы он лежал внутри соответствующего каталога, и вызывает `self.file` с явным типом `text/javascript; charset=utf-8` или `text/css; charset=utf-8` (расширить `file(self, p, ctype=None)`).
- [ ] **Step 4: Запустить тесты**. Ожидается PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: serve /js and /css with explicit content types"`

---

### Task 2: Токены, темы, контраст

**Files:**
- Create: `css/tokens.css`, `css/base.css`, `css/components.css`, `tests/contrast.py`, `tests/test_contrast.py`
- Modify: `index.html` (убрать `<style>`, подключить три файла)

**Interfaces:**
- Produces: токены `--ink --panel --raise --line --line2 --text --mute --ph --amber --amber-ink --danger --ok`; переопределения под `:root[data-theme=light]`, `:root[data-contrast=high]` и их сочетание; `:root[data-targets=large]` (минимум 44 px, `.sw` 52×44); `:root{font-size:16px}` с `[data-scale=125]` 20px и `[data-scale=150]` 24px; `tests/contrast.py: ratio(fg: str, bg: str) -> float`, `load_tokens(css: str, theme: str, contrast: str) -> dict[str, str]`.

- [ ] **Step 1: Написать тесты**

```python
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("contrast", ["normal", "high"])
def test_token_pairs_meet_wcag(theme, contrast):
    t = load_tokens(open("css/tokens.css").read(), theme, contrast)
    for fg in ("text", "mute", "ph", "danger", "ok", "amber"):
        assert ratio(t[fg], t["ink"]) >= 4.5 and ratio(t[fg], t["raise"]) >= 4.5, fg
    for border in ("line", "line2"):
        assert ratio(t[border], t["ink"]) >= 3, border
    assert ratio(t["amber-ink"], t["amber"]) >= 4.5

def test_ratio_known_value():
    assert round(ratio("#6d748a", "#1a1e2a"), 2) == 3.57   # старый placeholder (пункт 1)
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_contrast.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** вынос CSS из `index.html`; все `font-size` в px переводятся в rem (деление на 16); `--line`/`--line2` и поля получают непрозрачные цвета с контрастом ≥ 3:1; значения `--mute` и `--ph` подбираются так, чтобы тест проходил во всех 4 сочетаниях; `load_tokens` разбирает блоки токенов и применяет переопределения в порядке theme, затем contrast.
- [ ] **Step 4: Запустить тесты и `python -m pytest tests/test_smoke.py`**. Ожидается PASS, внешний вид в тёмной теме по умолчанию не изменился заметно.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: css tokens, light and high-contrast themes, rem sizing"`

---

### Task 3: `prefs.js` и ранний скрипт

**Files:**
- Create: `js/a11y/prefs.js`, `tests/test_prefs.py`
- Modify: `index.html` (inline-скрипт в `<head>`, подключение `main.js`), `js/main.js`

**Interfaces:**
- Produces: `DEFAULTS = {scale: 100, contrast: 'normal', theme: 'dark', targets: 'normal', keys: true}`; `loadPrefs(): Prefs`; `savePrefs(patch: Partial<Prefs>): Prefs`; `applyPrefs(p: Prefs, root?: HTMLElement): void` (ставит `data-scale|contrast|theme|targets`, `theme=system` вычисляет через `matchMedia`); `window.MH.prefs = {loadPrefs, savePrefs, applyPrefs}`.

- [ ] **Step 1: Написать тесты**

```python
def test_prefs_applied_before_domcontentloaded(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs', JSON.stringify({scale:150, contrast:'high', theme:'light', targets:'large'}))")
    page.add_init_script("document.addEventListener('DOMContentLoaded',()=>window.__a=document.documentElement.dataset.scale)")
    page.goto(server.url)
    assert page.evaluate("window.__a") == "150"
    assert page.evaluate("getComputedStyle(document.documentElement).fontSize") == "24px"

def test_corrupted_json_falls_back_to_defaults(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs','{broken')")
    page.goto(server.url)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"

def test_storage_blocked_does_not_break(server, page):
    page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked')}})")
    errors = []; page.on("pageerror", lambda e: errors.append(e))
    page.goto(server.url)
    assert not errors and page.locator("nav a").count() == 5

def test_save_prefs_roundtrip(server, page):
    page.goto(server.url)
    assert page.evaluate("MH.prefs.savePrefs({scale:125}).scale") == 125
    page.reload(); assert page.evaluate("document.documentElement.dataset.scale") == "125"
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_prefs.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** `prefs.js` с `try/catch` вокруг каждого обращения к `localStorage`, валидацией значений по списку допустимых; в `<head>` короткий inline-скрипт (чтение `mh.prefs` в `try`, установка `data-*`) до подключения CSS.
- [ ] **Step 4: Запустить тесты**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: display prefs in localStorage applied before paint"`

---

### Task 4: Ядро, legacy, роутинг, skip-link

**Files:**
- Create: `js/core/dom.js`, `js/core/api.js`, `js/legacy.js` (содержимое inline-скрипта `index.html` без изменений логики), `tests/test_route.py`
- Modify: `index.html` (каркас: skip-link, скрытые `h1` у разделов, `<main id="main" tabindex="-1">`), `js/main.js`

**Interfaces:**
- Produces: `$(id: string): HTMLElement`, `qa(sel: string): HTMLElement[]`, `esc(s: unknown): string`, `delegate(root: Element, event: string, handlers: Record<string, (el: HTMLElement, e: Event) => void>): void` (диспетчер по `data-action`); `api(url: string, body?: object): Promise<any>`; `onConnection(fn: (online: boolean) => void): void`; `startPolling(fn: () => Promise<void>): void` (интервал 1000 мс, 5000 мс пока офлайн); `afterRoute(view: string): void` (ставит `document.title = "<Раздел> — MediaHub"`, фокусирует `h1` раздела); `window.MH = {api, onConnection, startPolling, afterRoute, esc, ...}`.
- Consumes: ничего.

- [ ] **Step 1: Написать тесты**

```python
VIEWS = {"library": "Библиотека", "inbox": "Входящие", "downloads": "Загрузки", "games": "Игры", "settings": "Настройки"}

@pytest.mark.parametrize("view,name", VIEWS.items())
def test_route_sets_title_and_focuses_heading(server, page, view, name):
    page.goto(server.url + "/#" + view)
    assert page.title() == f"{name} — MediaHub"
    assert page.evaluate("document.activeElement.tagName") == "H1"

def test_skip_link_is_first_tab_stop_and_moves_focus(server, page):
    page.goto(server.url); page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Перейти к содержимому"
    page.keyboard.press("Enter"); assert page.evaluate("document.activeElement.id") == "main"

def test_api_failure_reports_offline_without_unhandled_rejection(server, page):
    errors = []; page.on("pageerror", lambda e: errors.append(e)); page.goto(server.url)
    page.route("**/api/jobs", lambda r: r.abort())
    page.wait_for_timeout(2500)
    assert not errors and page.evaluate("MH.__online") is False
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_route.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать**
  - Перенос inline-скрипта в `legacy.js`, подключение: `<script type="module" src="/js/main.js">` перед `<script defer src="/js/legacy.js">`.
  - В `legacy.js` заменить локальные `api` на `MH.api`, `setInterval(poll,1000)` на `MH.startPolling(poll)`, конец `route()` на вызов `MH.afterRoute(cur)`.
  - `api()` ловит сбои `fetch` и разбора JSON, выставляет `MH.__online` и вызывает слушателей `onConnection` при смене состояния; в офлайне возвращает отклонённый промис с `Error('offline')`, а `startPolling` его проглатывает.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: es-module core, legacy bridge, route title and focus, skip link"`

---

### Task 5: Центр уведомлений

**Files:**
- Create: `js/a11y/announce.js`, `tests/test_notify.py`
- Modify: `index.html` (live-области `#mh-live-polite`, `#mh-live-assertive`, кнопка `#bellBtn` в боковой панели, `<dialog id="logDlg">`), `js/legacy.js` (`toast(t,label,fn)` вызывает `MH.notify`), `js/main.js` (подписка на `onConnection`)

**Interfaces:**
- Consumes: `onConnection`, `esc` из Task 4.
- Produces: `announce(text: string, kind?: 'polite'|'assertive'): void`; `notify(text: string, opts?: {kind?: 'info'|'error', action?: {label: string, fn: () => void}, sticky?: boolean}): number`; `dismiss(id: number): void`; `getLog(): {id: number, text: string, kind: string, ts: number, action?: {label: string}}[]`; `openLog(): void`.

- [ ] **Step 1: Написать тесты** (время через `page.clock.install()`)

```python
def test_info_toast_lives_8s(server, page):
    page.clock.install(); page.goto(server.url)
    page.evaluate("MH.notify('Сохранено')")
    page.clock.run_for(7500); assert page.locator(".toast").count() == 1
    page.clock.run_for(1000); assert page.locator(".toast").count() == 0

def test_hover_pauses_dismissal(server, page):
    page.clock.install(); page.goto(server.url); page.evaluate("MH.notify('Сохранено')")
    page.locator(".toast").hover(); page.clock.run_for(20000)
    assert page.locator(".toast").count() == 1

def test_error_is_assertive_and_sticky(server, page):
    page.clock.install(); page.goto(server.url); page.evaluate("MH.notify('Сбой', {kind:'error'})")
    page.clock.run_for(60000)
    assert page.locator(".toast").count() == 1 and "Сбой" in page.locator("#mh-live-assertive").inner_text()

def test_log_keeps_last_50(server, page):
    page.goto(server.url); page.evaluate("for(let i=0;i<60;i++)MH.notify('m'+i)")
    assert page.evaluate("MH.getLog().length") == 50 and page.evaluate("MH.getLog()[0].text") == "m10"

def test_escape_dismisses_toast_and_bell_opens_log_with_action(server, page):
    page.goto(server.url); page.evaluate("MH.notify('Готово',{action:{label:'Загрузки',fn:()=>location.hash='#downloads'}})")
    page.keyboard.press("Escape"); assert page.locator(".toast").count() == 0
    page.locator("#bellBtn").click(); page.get_by_role("button", name="Загрузки").click()
    assert page.url.endswith("#downloads")

def test_connection_lost_and_restored(server, page):
    page.goto(server.url); page.route("**/api/jobs", lambda r: r.abort()); page.wait_for_timeout(2500)
    assert "Связь с MediaHub потеряна" in page.locator("#mh-live-assertive").inner_text()
    page.unroute("**/api/jobs"); page.wait_for_timeout(6500)
    assert "Связь восстановлена" in page.locator("#mh-live-polite").inner_text()
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_notify.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** модуль по сигнатурам; тост `role="status"`, текст через `textContent` (без `innerHTML`), пауза таймера на `mouseenter`/`focusin`; журнал и панель на `<dialog>`; `main.js` добавляет в `window.MH` функции `notify`, `announce`, `dismiss`, `getLog`, `openLog` и вызывает `notify('Связь с MediaHub потеряна', {kind:'error', sticky:true})` при `online=false` и `notify('Связь восстановлена')` с закрытием прежнего при `true`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: notification center with log and live regions"`

---

### Task 6: Общие элементы `ui/*`

**Files:**
- Create: `js/ui/chip.js`, `switch.js`, `dialog.js`, `field.js`, `progress.js`, `tabs.js`, `cardbtn.js`, `tests/test_ui.py`

**Interfaces:**
- Produces (все `*Html` возвращают строку с экранированным текстом):
  - `chipHtml(label: string, o: {pressed: boolean, count?: number, action: string, value?: string, extraClass?: string}): string`
  - `switchHtml(id: string, label: string, checked: boolean): string` (`<input type=checkbox role=switch class=sw aria-label>`)
  - `openDialog(dlg: HTMLDialogElement, opener?: Element | null): void`, `closeDialog(dlg: HTMLDialogElement): void` (возвращает фокус)
  - `fieldError(input: HTMLInputElement | HTMLTextAreaElement, message: string): void`, `clearFieldError(input): void` (`aria-invalid`, `aria-describedby`, фокус, `announce`)
  - `progressHtml(pct: number, label: string): string` (`role=progressbar`, `aria-valuemin=0 aria-valuemax=100 aria-valuenow`), `milestone(prevPct: number, nextPct: number, step?: number): number | null`
  - `initTabs(tablist: HTMLElement, onSelect: (id: string) => void): void` (roving tabindex, стрелки, Home/End, `aria-controls`)
  - `cardButtonHtml(o: {id: string | number, label: string, inner: string}): string` (`role=button tabindex=0 data-card data-id aria-label`)

- [ ] **Step 1: Написать тесты** (страница `/`, `page.evaluate` с `import('/js/ui/...')`)

```python
def test_chip_html_has_pressed_and_escapes(server, page):
    page.goto(server.url)
    h = page.evaluate("import('/js/ui/chip.js').then(m=>m.chipHtml('<b>Видео</b>',{pressed:true,count:3,action:'kind',value:'video'}))")
    assert 'aria-pressed="true"' in h and "<b>Видео" not in h and "&lt;b&gt;" in h

```

И параметризованный тест порога прогресса:

```python
@pytest.mark.parametrize("a,b,want", [(0, 24, None), (20, 30, 25), (24, 100, 100), (30, 40, None)])
def test_milestone(server, page, a, b, want):
    page.goto(server.url)
    assert page.evaluate(f"import('/js/ui/progress.js').then(m=>m.milestone({a},{b}))") == want
```

Остальные тесты: `test_field_error_sets_aria_and_focuses` (после `fieldError` у поля `aria-invalid="true"`, `aria-describedby` указывает на элемент с текстом, `document.activeElement` — поле); `test_tabs_arrow_keys_move_selection` (ArrowRight переводит `aria-selected` и фокус, Home возвращает на первую); `test_dialog_returns_focus_to_opener`; `test_progress_html_attrs`.

- [ ] **Step 2: Запустить `python -m pytest tests/test_ui.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** модули по сигнатурам; `fieldError` создаёт `<p id="<input.id>-err" class="field-err">` после поля, текст берёт через `textContent`.
- [ ] **Step 4: Запустить тесты**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: shared accessible ui primitives"`

---

### Task 7: Горячие клавиши

**Files:**
- Create: `js/a11y/keys.js`, `tests/test_keys.py`
- Modify: `index.html` (`<dialog id="helpDlg">`), `js/legacy.js` (удалить старый обработчик `/`), `js/main.js` (`initKeys`)

**Interfaces:**
- Consumes: `loadPrefs` (Task 3), `openLog` (Task 5), `openDialog` (Task 6).
- Produces: `createSequencer(timeoutMs?: number): {feed(key: string, now: number): string | null}` (возвращает `'nav:library|inbox|downloads|games|settings'`, `'log'` или `null`); `initKeys(deps: {enabled: () => boolean, go: (view: string) => void, focusSearch: () => void, openLog: () => void, openHelp: () => void}): void`.

- [ ] **Step 1: Написать тесты**

```python
def test_sequencer_pure(server, page):
    page.goto(server.url)
    r = page.evaluate("""import('/js/a11y/keys.js').then(m=>{const s=m.createSequencer(1500);
      return [s.feed('g',0), s.feed('l',100), s.feed('g',200), s.feed('d',2000), s.feed('g',3000), s.feed('n',3100)]})""")
    assert r == [None, "nav:library", None, None, None, "log"]

def test_g_then_d_navigates(server, page):
    page.goto(server.url); page.keyboard.press("g"); page.keyboard.press("d")
    assert page.url.endswith("#downloads")

def test_ignored_in_inputs_and_with_modifiers(server, page):
    page.goto(server.url); page.locator("#q").focus(); page.keyboard.type("gd")
    assert not page.url.endswith("#downloads") and page.input_value("#q") == "gd"
    page.locator("body").click(); page.keyboard.press("Control+g"); page.keyboard.press("d")
    assert not page.url.endswith("#downloads")

def test_switch_off_disables_keys(server, page):
    page.add_init_script("localStorage.setItem('mh.prefs', JSON.stringify({keys:false}))")
    page.goto(server.url); page.keyboard.press("g"); page.keyboard.press("d")
    assert not page.url.endswith("#downloads")

def test_question_mark_opens_help_and_slash_focuses_search(server, page):
    page.goto(server.url); page.keyboard.press("?")
    assert page.locator("#helpDlg").is_visible(); page.keyboard.press("Escape")
    page.keyboard.press("/"); assert page.evaluate("document.activeElement.id") == "q"
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_keys.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** секвенсор как чистую функцию состояния (префикс `g`, сброс по таймауту и по любой другой клавише); `initKeys` вешает `keydown` на `document`, пропускает `INPUT/TEXTAREA/SELECT/contenteditable` и события с `ctrlKey/altKey/metaKey`, читает `enabled()` на каждое нажатие; `j/k` переносят фокус по `[data-card]`; справка перечисляет клавиши и состоит из таблицы с подписью.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: g-sequence hotkeys with help and off switch"`

---

### Task 8: Раздел «Настройки»

**Files:**
- Create: `js/views/settings.js`, `tests/test_settings.py`
- Modify: `index.html` (разметка раздела), `js/legacy.js` (удалить перенесённый код)

**Interfaces:**
- Consumes: `switchHtml`, `savePrefs`, `announce`.
- Produces: `initSettings(): void`; `loadSettings(): Promise<void>` вызывается из `afterRoute('settings')`.

- [ ] **Step 1: Написать тесты**

```python
SET = ["games_check_hours","manga_via","folder","res","afmt","subs_on","subs_langs","thumbs","skip","workers","limit_mb","depth","maxp","videos","show_browser","cookie_file","cookie_browser","games_root"]

@pytest.mark.parametrize("key", SET)
def test_every_setting_has_accessible_name(server, page, key):
    page.goto(server.url + "/#settings")
    name = page.evaluate(f"(()=>{{const e=document.getElementById('s_{key}'); return e.labels&&e.labels[0]?e.labels[0].textContent.trim():(e.getAttribute('aria-label')||'')}})()")
    assert name

def test_scale_pref_changes_root_font_and_announces(server, page):
    page.goto(server.url + "/#settings"); page.get_by_label("Размер текста").select_option("150")
    assert page.evaluate("getComputedStyle(document.documentElement).fontSize") == "24px"
    assert "Размер текста" in page.locator("#mh-live-polite").inner_text()

def test_hotkeys_switch_present_and_persists(server, page):
    page.goto(server.url + "/#settings"); page.get_by_role("switch", name="Горячие клавиши").uncheck()
    page.reload(); assert page.evaluate("JSON.parse(localStorage.getItem('mh.prefs')).keys") is False

def test_settings_axe_clean(server, page):
    page.goto(server.url + "/#settings"); assert run_axe(page) == []
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_settings.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** строки `.sr` как `<label for>` на заголовок и поле (подсказка `<small>` через `aria-describedby`); новая группа «Отображение»: размер текста (100/125/150 %), контраст, тема, крупные цели, «Горячие клавиши»; изменения идут через `savePrefs` + `applyPrefs` + `announce("Размер текста: 150 %")`; серверное сохранение `save()` остаётся как было, уведомление «Сохранено» идёт через `notify`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: accessible settings view with display preferences"`

---

### Task 9: Раздел «Библиотека» и диалог «Добавить»

**Files:**
- Create: `js/views/library.js`, `js/views/add.js`, `tests/test_library.py`
- Modify: `index.html`, `js/legacy.js`

**Interfaces:**
- Consumes: `chipHtml`, `cardButtonHtml`, `fieldError`, `delegate`, `notify`, `initTabs`.
- Produces: `initLibrary(): void`, `loadLibrary(): Promise<void>`, `openAdd(): void`.

- [ ] **Step 1: Написать тесты** (данные кладёт `server.add_item`)

```python
EVIL = '"><img src=x onerror=window.__x=1> <b>Тест</b>'

def test_titles_are_escaped_in_labels(server, page):
    server.add_item(title=EVIL, kind="video")
    page.goto(server.url)
    assert page.evaluate("window.__x") is None and page.locator("b", has_text="Тест").count() == 0

def test_kind_chips_expose_pressed(server, page):
    server.add_item(title="a", kind="video"); page.goto(server.url)
    c = page.get_by_role("button", name="Видео"); c.click()
    assert c.get_attribute("aria-pressed") == "true"

def test_library_has_h1(server, page):
    page.goto(server.url); assert page.locator("#v-library h1").count() == 1

def test_add_error_is_tied_to_field(server, page):
    page.goto(server.url); page.get_by_role("button", name="Добавить").click(); page.get_by_role("button", name="Скачать").click()
    f = page.locator("#urls")
    assert f.get_attribute("aria-invalid") == "true" and page.evaluate("document.activeElement.id") == "urls"
    assert "ссылк" in page.locator("#" + f.get_attribute("aria-describedby")).inner_text()

def test_txt_picker_is_button_and_keyboard_operable(server, page):
    page.goto(server.url); page.get_by_role("button", name="Добавить").click(); page.locator("#more summary").click()
    with page.expect_file_chooser(): page.get_by_role("button", name="Выбрать файл .txt").press("Enter")

def test_card_actions_visible_on_touch(server, touch_page):
    server.add_item(title="a", kind="video"); touch_page.goto(server.url)
    assert touch_page.evaluate("getComputedStyle(document.querySelector('.act')).opacity") == "1"

def test_game_card_is_button_not_link(server, page):
    server.add_item(title="g", kind="game"); page.goto(server.url)
    assert page.locator("a[href='#']").count() == 0

def test_kind_radiogroup_arrow_keys(server, page):
    page.goto(server.url); page.get_by_role("button", name="Добавить").click()
    page.get_by_role("radio", name="Видео").focus(); page.keyboard.press("ArrowRight")
    assert page.get_by_role("radio", name="Аудио").get_attribute("aria-checked") == "true"
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_library.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** перенос рисования библиотеки в `library.js` с делегированием по `data-action` (`kind`, `open`, `edit`, `delete`, `reveal`, `download`); игры в карточке — кнопка, не ссылка; добавление, правка и удаление — через `openDialog`; в `add.js` `fieldError` вместо тоста для пустых ссылок, `<button>` вместо `label tabindex`, группа типов с roving tabindex; CSS `@media (pointer: coarse){.act{opacity:1}}`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: accessible library and add dialog"`

---

### Task 10: Раздел «Загрузки» и нижняя полоса

**Files:**
- Create: `js/views/downloads.js`, `tests/test_downloads.py`
- Modify: `index.html`, `js/legacy.js`

**Interfaces:**
- Consumes: `progressHtml`, `milestone`, `announce`, `notify`, `startPolling`.
- Produces: `jobAnnouncements(prev: Job[], next: Job[]): string[]` с `Job = {id: number, title: string, status: string, pct: number}`; `drawJobs(J: Job[]): void`; `drawBar(J: Job[]): void`.

- [ ] **Step 1: Написать тесты**

```python
def _ann(page, prev, nxt):
    return page.evaluate("([a,b])=>import('/js/views/downloads.js').then(m=>m.jobAnnouncements(a,b))", [prev, nxt])

def test_milestones_start_finish_error(server, page):
    page.goto(server.url)
    j = lambda **k: {"id": 1, "title": "Видео", "status": "качается", "pct": 0, **k}
    assert _ann(page, [], [j()]) == ["Видео: началась загрузка"]
    assert _ann(page, [j(pct=20)], [j(pct=30)]) == ["Видео: 25 %"]
    assert _ann(page, [j(pct=30)], [j(pct=40)]) == []
    assert _ann(page, [j(pct=90)], [j(pct=100, status="готово")]) == ["Видео: готово"]
    assert _ann(page, [j(pct=10)], [j(status="ошибка: сеть")]) == ["Видео: ошибка: сеть"]

def test_bottom_bar_is_link_without_status_role(server, page):
    page.goto(server.url)
    page.evaluate("import('/js/views/downloads.js').then(m=>m.drawBar([{id:1,title:'v',status:'качается',pct:10,speed:0}]))")
    bar = page.locator("#bar"); assert bar.get_attribute("role") is None and bar.locator("a[href='#downloads']").count() == 1

def test_job_progressbar_has_role_and_value(server, page):
    page.goto(server.url + "/#downloads")
    page.evaluate("import('/js/views/downloads.js').then(m=>m.drawJobs([{id:1,title:'v',kind:'video',status:'качается',pct:42}]))")
    pb = page.get_by_role("progressbar"); assert pb.get_attribute("aria-valuenow") == "42"
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_downloads.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** перенос рисования; нижняя полоса становится `<a href="#downloads">` без `role=status`; каждый опрос сравнивает предыдущее и новое состояние через `jobAnnouncements` и отправляет результат в `announce`, ошибки дополнительно в `notify({kind:'error'})`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: accessible downloads with milestone announcements"`

---

### Task 11: Раздел «Входящие»

**Files:**
- Create: `js/views/inbox.js`, `tests/test_inbox.py`
- Modify: `index.html`, `js/legacy.js`

**Interfaces:**
- Consumes: `chipHtml`, `delegate`, `announce`.
- Produces: `initInbox(): void`, `loadInbox(): Promise<void>`, `rowLabel(r: {title: string}): string` (возвращает `Включить в план: <title>`).

- [ ] **Step 1: Написать тесты** (данные через маршрут Playwright на `/api/inbox` с одним пакетом из 2 вкладок)

```python
def test_row_checkboxes_have_distinct_names(server, page):
    stub_inbox(page, titles=["Альфа", "Бета"]); page.goto(server.url + "/#inbox")
    assert page.get_by_role("checkbox", name="Включить в план: Альфа").count() == 1
    assert page.get_by_role("checkbox", name="Включить в план: Бета").count() == 1

def test_filter_chips_pressed_and_summary_live(server, page):
    stub_inbox(page, titles=["Альфа", "Бета"]); page.goto(server.url + "/#inbox")
    assert page.locator(".bsum").get_attribute("aria-live") == "polite"
    page.get_by_role("checkbox", name="Включить в план: Альфа").uncheck()
    assert "Выбрано 1 из 2" in page.locator(".bsum").inner_text()
    c = page.get_by_role("button", name="Новое"); c.click(); assert c.get_attribute("aria-pressed") == "true"

def test_inbox_axe_clean(server, page):
    stub_inbox(page, titles=["Альфа"]); page.goto(server.url + "/#inbox"); assert run_axe(page) == []
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_inbox.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** перенос с сохранением логики возврата фокуса на `select` после перерисовки; чипы через `chipHtml`; `.bsum` получает `aria-live="polite"`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: accessible inbox view"`

---

### Task 12: Раздел «Игры» и панель-диалог

**Files:**
- Create: `js/views/games.js`, `tests/test_games.py`
- Modify: `index.html` (`<dialog id="gpanel">`), `js/legacy.js` (legacy теперь пуст: удалить файл и подключение)

**Interfaces:**
- Consumes: `cardButtonHtml`, `chipHtml`, `initTabs`, `openDialog`, `closeDialog`.
- Produces: `initGames(): void`, `loadGames(): Promise<void>`, `openPanel(id: number): void`, `closePanel(): void`.

- [ ] **Step 1: Написать тесты**

```python
def test_game_card_has_button_role_and_opens_panel(server, page):
    server.add_item(title="Игра", kind="game"); page.goto(server.url + "/#games")
    card = page.get_by_role("button", name="Игра: не скачано"); card.press("Enter")
    assert page.locator("#gpanel").evaluate("e=>e.open")

def test_panel_traps_focus_and_returns_it(server, page):
    server.add_item(title="Игра", kind="game"); page.goto(server.url + "/#games")
    card = page.get_by_role("button", name="Игра: не скачано"); card.focus(); card.press("Enter")
    for _ in range(40): page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('#gpanel')") is not None
    page.keyboard.press("Escape"); assert page.evaluate("document.activeElement.dataset.id") is not None

def test_backdrop_click_closes_panel(server, page):
    server.add_item(title="Игра", kind="game"); page.goto(server.url + "/#games")
    page.get_by_role("button", name="Игра: не скачано").click(); page.mouse.click(1200, 400)
    assert not page.locator("#gpanel").evaluate("e=>e.open")

def test_games_tabs_arrow_navigation(server, page):
    page.goto(server.url + "/#games"); page.get_by_role("tab", name="Библиотека").focus(); page.keyboard.press("ArrowRight")
    assert page.get_by_role("tab", name="Версии и чистка").get_attribute("aria-selected") == "true"

def test_games_axe_clean(server, page):
    server.add_item(title="Игра", kind="game"); page.goto(server.url + "/#games"); assert run_axe(page) == []
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_games.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** панель как `<dialog>` с прежним слайдом (CSS по `[open]`) и закрытием по клику на подложку (`e.target === dlg`); открытие через `openDialog(dlg, card)`; жанровые чипы через `chipHtml`; вкладки через `initTabs`.
- [ ] **Step 4: Запустить `python -m pytest tests -q`**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: accessible games view, panel as dialog; remove legacy.js"`

---

### Task 13: Читалка и всплывающее окно расширения

**Files:**
- Modify: `reader.html`, `extension/popup.html`, `extension/popup.css`
- Test: `tests/test_reader.py`

**Interfaces:**
- Consumes: `/css/tokens.css` (Task 2).

- [ ] **Step 1: Написать тесты**

```python
def test_reader_chapter_select_has_name_and_axe_clean(server, page):
    page.goto(server.url + "/m/999")
    assert page.locator("select#c").get_attribute("aria-label") == "Глава"
    assert run_axe(page) == []

def test_reader_uses_shared_tokens(server, page):
    page.goto(server.url + "/m/999")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()") != ""
```

- [ ] **Step 2: Запустить `python -m pytest tests/test_reader.py -v`**. Ожидается FAIL.
- [ ] **Step 3: Реализовать** в `reader.html`: подключение `/css/tokens.css`, `aria-label="Глава"`, `<main>` вокруг `#v`, `aria-label` у кнопок «Предыдущая глава» и «Следующая глава»; в `popup.html` проверить, что у группы и флажка есть имена (уже есть), и заменить цвета на контрастные значения из токенов (в `popup.css` значения копируются, подключения общего файла у расширения нет).
- [ ] **Step 4: Запустить тесты**. Ожидается PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "fix: reader and popup accessibility"`

---

### Task 14: Приёмочная матрица и документация

**Files:**
- Create: `tests/test_matrix.py`, `tests/test_rules.py`, `tests/test_keyboard_walk.py`, `docs/a11y-manual-stage1.md`
- Modify: `README.md` (раздел «Доступность»: режимы, клавиши, журнал)

**Interfaces:**
- Consumes: `run_axe`, `set_prefs`, `open_view` (Task 0).

- [ ] **Step 1: Написать тесты**

```python
COMBOS = [(t, c) for t in ("dark", "light") for c in ("normal", "high")]

@pytest.mark.parametrize("view", ["library", "inbox", "downloads", "games", "settings"])
@pytest.mark.parametrize("theme,contrast", COMBOS)
def test_axe_matrix(server, page, view, theme, contrast):
    set_prefs(page, theme=theme, contrast=contrast); open_view(page, server, view)
    assert run_axe(page) == []

@pytest.mark.parametrize("view", ["library", "inbox", "downloads", "games", "settings"])
def test_reflow_at_200_percent(server, page, view):
    page.set_viewport_size({"width": 640, "height": 512}); open_view(page, server, view)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

@pytest.mark.parametrize("view", ["library", "downloads", "settings"])
def test_large_targets_min_44(server, page, view):
    set_prefs(page, targets="large"); open_view(page, server, view)
    small = page.evaluate("""[...document.querySelectorAll('button,summary,select,nav a,[role=button],input.sw,.chip')]
        .filter(e=>e.offsetParent).map(e=>[e, e.getBoundingClientRect()]).filter(([e,r])=>r.width<44||r.height<44).map(([e])=>e.outerHTML.slice(0,80))""")
    assert small == []

def test_every_chip_pressed_and_no_empty_onclick(server, page):
    server.add_item(title="a", kind="video"); page.goto(server.url)
    assert page.evaluate("[...document.querySelectorAll('.chip,.gchip')].every(e=>e.hasAttribute('aria-pressed'))")
    assert page.evaluate("document.querySelectorAll('[onclick]').length") == 0
```

`test_keyboard_walk.py`: для каждого раздела нажимать Tab до возврата на skip-link, проверяя, что `document.activeElement` имеет видимый `outline-style != none` или `box-shadow`, и что ни один элемент с `[onclick]`, `[role=button]` или `a/button/input` не пропущен (сравнение списка интерактивных элементов с посещёнными).

- [ ] **Step 2: Запустить `python -m pytest tests -q`**. Ожидается: падения указывают на оставшиеся места, не покрытые Task 2–13.
- [ ] **Step 3: Исправить найденное** в соответствующих модулях; повторять до зелёного набора.
- [ ] **Step 4: Написать `docs/a11y-manual-stage1.md`**: 10 сценариев (настройки, фильтры, добавление ссылки с ошибкой, загрузка, панель игры, уведомления и журнал, смена раздела, горячие клавиши и справка, потеря связи, режимы отображения) × NVDA с Firefox и Яндекс Браузером, колонки «ожидаемое озвучивание» и «результат / подпись»; обновить `README.md`.
- [ ] **Step 5: Запустить `python -m pytest tests -q`**. Ожидается PASS целиком.
- [ ] **Step 6: Commit** `git add -A && git commit -m "test: acceptance matrix, manual checklist, docs"`

---

## Покрытие пунктов аудита

1, 2 → Task 2; 3, 7, 14, 22 → Task 9; 4, 9, 12 → Task 4; 5, 19 → Task 10; 6, 18, 21 → Task 12 (и Task 9 для radiogroup); 8, 20 → Task 5 (сводки: Task 9, 11); 10 → Task 2 и Task 14; 11 → Task 7; 13 → Task 8; 15 → Task 13; 16, 17 → Task 11 (и Task 9, 12 для чипов).
