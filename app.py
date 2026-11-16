# MediaHub v2: локальный загрузчик + библиотека. Движок — yt-dlp[default], ffmpeg/deno берутся из папки ffmpeg рядом.
import sys, math, base64, hmac, secrets, http.client, json, os, re, subprocess, shutil, sqlite3, threading, queue, time, webbrowser, urllib.request, itertools, http.cookiejar, mimetypes
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

mimetypes.add_type('image/avif', '.avif'); BASE = Path(__file__).parent; sys.path.insert(0, str(BASE)); FF = BASE / 'ffmpeg'; CFG = BASE / 'settings.json'
if FF.exists(): os.environ['PATH'] = str(FF) + os.pathsep + os.environ['PATH']  # ffmpeg, ffprobe, deno
cfg = {'folder': str(Path.home() / 'Downloads' / 'MediaHub'), 'workers': 3, 'skip': True, 'cookie_file': '', 'cookie_browser': '', 'games_root': '', 'show_browser': False, 'browser': 'msedge', 'limit_mb': 0, 'manga_via': 'auto', 'games_check_hours': 0, 'game_marker': True, 'lan': False, 'lan_pin_salt': '', 'lan_pin_hash': '', 'feed_hours': 0, 'feed_delay': 3, 'feed_checked': 0, 'feed_last': '',
       'res': 'best', 'afmt': 'mp3', 'subs_on': False, 'subs_langs': 'ru,en', 'thumbs': True, 'depth': 1, 'maxp': 100, 'videos': True}
if CFG.exists(): cfg.update(json.loads(CFG.read_text('utf-8')))
db = sqlite3.connect(BASE / 'library.db', check_same_thread=False); db.row_factory = sqlite3.Row; lock = threading.Lock()
db.execute('create table if not exists items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp, thumb)')
try: db.execute('alter table items add column thumb')
except sqlite3.OperationalError: pass
db.execute('create table if not exists progress(slug primary key, cid, page int)')
try: db.execute('alter table progress add column updated real')
except sqlite3.OperationalError: pass
db.execute('create table if not exists playpos(item_id integer primary key, pos real not null, dur real not null default 0, updated real not null)')
db.execute("create table if not exists usermeta(item_id integer primary key, fav int not null default 0, status text not null default '', rating int, tags text not null default '', descr text not null default '', cover text not null default '')")
# номера удалённых записей SQLite использует повторно: без триггеров личные данные и позиция просмотра прилипали бы к новой записи
db.execute("create trigger if not exists usermeta_gc after delete on items begin delete from usermeta where item_id=old.id; end")
db.execute("create trigger if not exists playpos_gc after delete on items begin delete from playpos where item_id=old.id; end")
# «эта папка = эта карточка»: запоминается между запусками; method: manual (вы привязали), name (по названию), marker (по файлу .mediahub.json в папке)
db.execute("create table if not exists links(path text primary key, item_id integer not null, method text not null, at real not null)")
db.execute("create index if not exists links_item on links(item_id)")
db.execute("create trigger if not exists links_gc after delete on items begin delete from links where item_id=old.id; end")
# лента обновлений: события (игры, манга, видео) и отслеживаемые каналы/плейлисты; key делает событие уникальным: повторная проверка не плодит записи
db.execute("create table if not exists feed(id integer primary key autoincrement, kind text not null, key text not null unique, item_id integer, title text, detail text, url text, action text, payload text default '{}', at real not null, seen integer default 0)")
db.execute("create table if not exists watch(id integer primary key autoincrement, url text not null unique, title text default '', seen text default '[]', baselined integer default 0, checked real default 0, added real not null, error text default '')")
db.execute("create trigger if not exists feed_gc after delete on items begin delete from feed where item_id=old.id; end")
Q, jobs, ids, prev, _op = queue.Queue(), {}, itertools.count(1), {}, [None]
VID = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv', '.m4v'}; AUD = {'.mp3', '.m4a', '.opus', '.flac', '.wav', '.ogg', '.aac'}

def sql(s, a=()):
    with lock:
        r = db.execute(s, a).fetchall(); db.commit(); return r
STATUSES = ('', 'new', 'doing', 'done')   # не начато / в процессе / завершено (подписи зависят от типа: прохожу, читаю, смотрю)
def um_row(r):
    r = r or {}; return {'fav': bool(r.get('fav')), 'status': r.get('status') or '', 'rating': r.get('rating'), 'tags': [t for t in (r.get('tags') or '').split('\n') if t], 'descr': r.get('descr') or '', 'cover': r.get('cover') or ''}
def umeta(i):
    r = sql('select * from usermeta where item_id=?', (i,)); return um_row(dict(r[0]) if r else None)
def umeta_all(): return {r['item_id']: um_row(dict(r)) for r in sql('select * from usermeta')}
def clean_tags(v):
    out = []
    for t in (v if isinstance(v, list) else re.split(r'[,\n;]+', str(v or ''))):
        t = re.sub(r'\s+', ' ', str(t)).strip().lstrip('#')[:40]
        if t and t.casefold() not in [x.casefold() for x in out]: out.append(t)
    return out[:30]
def umeta_set(i, d):  # только перечисленные поля, остальное не трогаем
    cur = umeta(i)
    if 'fav' in d: cur['fav'] = bool(d['fav'])
    if d.get('status') in STATUSES: cur['status'] = d['status']
    if 'rating' in d: v = d['rating']; cur['rating'] = None if v in (None, '') else max(0, min(10, int(v)))
    if 'tags' in d: cur['tags'] = clean_tags(d['tags'])
    if 'descr' in d: cur['descr'] = str(d['descr'] or '')[:5000]
    if 'cover' in d: cur['cover'] = str(d['cover'] or '')
    sql('insert into usermeta(item_id,fav,status,rating,tags,descr,cover) values(?,?,?,?,?,?,?) on conflict(item_id) do update set fav=excluded.fav,status=excluded.status,rating=excluded.rating,tags=excluded.tags,descr=excluded.descr,cover=excluded.cover',
        (i, int(cur['fav']), cur['status'], cur['rating'], '\n'.join(cur['tags']), cur['descr'], cur['cover'])); return cur
def cover_of(r, um=None):  # своя обложка важнее скачанной; ?v= сбрасывает кэш браузера после замены
    c = (um if um is not None else umeta(r['id'])).get('cover') or ''
    if c and Path(c).exists(): return f"/c/{r['id']}?v={int(Path(c).stat().st_mtime)}"
    return f"/t/{r['id']}" if r['thumb'] else ''
def safe(s): return re.sub(r'[\\/:*?"<>|]+', '_', str(s or '')).strip()[:100] or 'Unknown'
def root(sub):
    p = Path(cfg['folder']) / sub; p.mkdir(parents=True, exist_ok=True); return p
def thumb_of(p):
    for e in ('.jpg', '.jpeg', '.png', '.webp'):
        if Path(p).with_suffix(e).exists(): return str(Path(p).with_suffix(e))
    return ''
def add(title, author, topic, kind, path, url, rt='', thumb=''):
    sz = sum(f.stat().st_size for f in Path(rt).rglob('*') if f.is_file()) if rt else os.path.getsize(path)
    sql('insert into items(title,author,topic,kind,path,root,url,size,thumb) values(?,?,?,?,?,?,?,?,?) on conflict(url) do update set title=excluded.title,path=excluded.path,root=excluded.root,size=excluded.size,thumb=excluded.thumb,author=case when items.kind=\'link\' then excluded.author else items.author end,topic=case when items.kind=\'link\' then excluded.topic else items.topic end,kind=excluded.kind',
        (title, author, topic, kind, str(path), str(rt), url, sz, thumb or ('' if rt else thumb_of(path))))
def scan():  # подхватывает файлы, которых нет в базе (в т.ч. скачанные раньше)
    have = {r['path'] for r in sql('select path from items')}
    for kind, sub, ex in (('video', 'Video', VID), ('audio', 'Audio', AUD)):
        d = root(sub)
        for f in d.rglob('*'):
            if f.suffix.lower() in ex and str(f) not in have and not re.search(r'\.f\d+\.', f.name):
                add(f.stem, f.parent.name if f.parent != d else 'Unknown', 'Разное', kind, f, 'file:' + str(f))

NOWIN = 0x08000000 if os.name == 'nt' else 0; _bf = [False]
def backfill():  # обложка-кадр для видео, у которых её нет (старые загрузки, обложки отключали)
    if _bf[0]: return
    _bf[0] = True
    try:
        ff = shutil.which('ffmpeg')
        if not ff: return
        for r in sql("select id,path from items where kind='video' and (thumb is null or thumb='')"):
            p = Path(r['path']); out = p.with_suffix('.jpg')
            if not p.exists(): continue
            for ss in ('5', '0'):  # сначала 5-я секунда, для коротких роликов первый кадр
                if out.exists(): break
                try: subprocess.run([ff, '-y', '-ss', ss, '-i', str(p), '-frames:v', '1', '-vf', 'scale=480:-2', '-q:v', '4', str(out)], capture_output=True, timeout=60, creationflags=NOWIN)
                except Exception: pass
            if out.exists(): sql('update items set thumb=? where id=?', (str(out), r['id']))
    finally: _bf[0] = False

def fmt(kind, r): return 'bestaudio/best' if kind == 'audio' else ('bv*+ba/b' if r == 'best' else f'bv*[height<={r}]+ba/b[height<={r}]')
def base():
    o = {'quiet': True, 'no_warnings': True, 'remote_components': ['ejs:github']}
    if cfg['cookie_file']: o['cookiefile'] = cfg['cookie_file']
    elif cfg['cookie_browser']: o['cookiesfrombrowser'] = (cfg['cookie_browser'],)
    if FF.exists(): o['ffmpeg_location'] = str(FF)
    return o

# ---------- видео / аудио ----------
def media(job):  # видео/аудио; плейлисты и каналы разворачиваются и качаются несколькими потоками сразу
    import yt_dlp
    audio = job['kind'] == 'audio'; n, errs, part, sp, lk = [0], [], {}, {}, threading.Lock(); st = {'done': 0, 'total': 1}
    class L:
        def debug(s, m): pass
        def warning(s, m): pass
        def error(s, m): errs.append(m)
    def post(d):
        if d['postprocessor'] == 'MoveFiles' and d['status'] == 'finished':
            i = d['info_dict']
            with lk: n[0] += 1
            add(i.get('title'), i.get('uploader') or i.get('channel') or 'Unknown',
                job['topic'] or (i.get('categories') or i.get('tags') or ['Разное'])[0], job['kind'], i['filepath'], i.get('webpage_url') or job['url'])
    def run(url, tid):
        def hook(d):
            if job['cancel']: raise yt_dlp.utils.DownloadCancelled('отменено')
            if d['status'] == 'downloading':
                t = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                with lk:
                    if t: part[tid] = d['downloaded_bytes'] / t
                    sp[tid] = d.get('speed') or 0; job['speed'] = sum(sp.values()); job['_ts'] = time.time(); job['eta'] = d.get('eta') or 0
                    job['title'] = d['info_dict'].get('title', ''); job['pct'] = min(99, int((st['done'] + sum(part.values())) * 100 / st['total']))
        o = base(); pps = []
        o.update({'format': fmt(job['kind'], job['res']), 'ignoreerrors': 'only_download', 'concurrent_fragment_downloads': 8, 'logger': L(),
                  'outtmpl': str(root('Audio' if audio else 'Video') / '%(uploader,channel|Unknown)s' / '%(title).120B.%(ext)s'),
                  'progress_hooks': [hook], 'postprocessor_hooks': [post]})
        if audio: pps.append({'key': 'FFmpegExtractAudio', 'preferredcodec': job['afmt']})
        else: o['merge_output_format'] = 'mp4'
        if job['subs'] and not audio:
            o.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=[x.strip() for x in job['subs'].split(',')], subtitlesformat='srt/best', sleep_interval_subtitles=1)
            pps.append({'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'})
        if job['thumbs']:
            o['writethumbnail'] = True; pps += [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'}, {'key': 'EmbedThumbnail'}]
        o['postprocessors'] = pps
        if float(cfg.get('limit_mb') or 0): o['ratelimit'] = int(float(cfg['limit_mb']) * 1048576 / max(1, min(st['total'], int(cfg.get('workers') or 3))))
        if cfg['skip']: o['download_archive'] = str(BASE / f"archive_{job['kind']}.txt")
        with yt_dlp.YoutubeDL(o) as y: y.download([url])
        with lk: st['done'] += 1; part.pop(tid, None); sp.pop(tid, None)
    urls = [job['url']]
    if not re.search(r'(youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+)$', job['url']):  # одиночное видео YouTube не проверяем: экономим запрос
        try:
            fo = base(); fo.update(extract_flat='in_playlist', skip_download=True)
            with yt_dlp.YoutubeDL(fo) as y: t = y.extract_info(job['url'], download=False)
            if t and t.get('_type') == 'playlist':
                us = [e.get('url') or e.get('webpage_url') for e in (t.get('entries') or []) if e]; us = [u for u in us if u and str(u).startswith('http')]
                if len(us) > 1: urls = us
        except Exception: pass
    st['total'] = len(urls)
    if len(urls) == 1: run(urls[0], 0)
    else:
        job['title'] = f'список: {len(urls)} видео'
        with ThreadPoolExecutor(max(1, int(cfg.get('workers') or 3))) as ex:
            for f in [ex.submit(run, u, k) for k, u in enumerate(urls)]:
                try: f.result()
                except Exception: pass
    scan(); backfill()
    if not n[0] and not job['cancel']:
        if errs: raise RuntimeError(errs[-1])
        job['final'] = 'пропущено: уже скачано'

# ---------- сайт офлайн (страницы + видео) ----------
UA = {'User-Agent': 'Mozilla/5.0'}
VEXT = ('.mp4', '.webm', '.m4v', '.mov', '.mkv', '.m3u8', '.mpd')
VH = re.compile(r'youtube\.com|youtu\.be|vimeo\.com|rutube\.ru|vk\.com/video|vkvideo\.ru|dailymotion\.com|ok\.ru/video|twitch\.tv|bilibili\.com|player\.', re.I)
SKIP = re.compile(r'\.(jpe?g|png|gif|webp|svg|pdf|zip|rar|7z|mp3|mp4|webm|css|js|ico|exe)(\?|$)', re.I)

def guard(u):  # блокируем localhost и локальную сеть (в т.ч. после редиректов)
    import socket, ipaddress
    p = urlparse(u)
    if p.scheme not in ('http', 'https') or not p.hostname: raise ValueError('bad url')
    if os.environ.get('MEDIAHUB_TEST_ALLOW_LOCAL') == '1': return
    for a in socket.getaddrinfo(p.hostname, p.port or 80):
        ip = ipaddress.ip_address(a[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise ValueError('локальный адрес заблокирован')

def guard_literal(u):  # быстрая проверка без DNS: понятно локальные адреса отклоняем сразу (полная guard() сработает при самой проверке)
    import ipaddress
    p = urlparse(u); h = (p.hostname or '').lower()
    if p.scheme not in ('http', 'https') or not h: raise ValueError('bad url')
    if h == 'localhost' or h.endswith(('.localhost', '.local', '.internal')): raise ValueError('локальный адрес заблокирован')
    try: ip = ipaddress.ip_address(h)
    except ValueError: return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise ValueError('локальный адрес заблокирован')

def opener():
    if not _op[0]:
        jar = http.cookiejar.MozillaCookieJar()
        if cfg['cookie_file']:
            try: jar.load(cfg['cookie_file'], ignore_discard=True, ignore_expires=True)
            except Exception: pass
        _op[0] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return _op[0]

def fetch(u):
    guard(u)
    with opener().open(urllib.request.Request(u, headers=UA), timeout=20) as r:
        guard(r.geturl()); return r.read(), r.headers.get('Content-Type', '')

def stream(job, u, dest, tot, t0):  # большие видеофайлы пишем кусками
    guard(u); dest.parent.mkdir(parents=True, exist_ok=True)
    with opener().open(urllib.request.Request(u, headers=UA), timeout=30) as r, open(dest, 'wb') as f:
        guard(r.geturl())
        while not job['cancel']:
            c = r.read(1 << 20)
            if not c: break
            f.write(c); tot[0] += len(c); job['speed'] = tot[0] / max(1, time.time() - t0)

def grab(job, u, out, vids):  # YouTube, Vimeo, VK, Rutube, потоки m3u8/mpd и т.д. через yt-dlp
    if u in vids: return vids[u]
    vids[u] = []
    try:
        import yt_dlp
        def hk(d):
            if job['cancel']: raise yt_dlp.utils.DownloadCancelled('отменено')
            if d['status'] == 'downloading': job['speed'] = d.get('speed') or 0; job['title'] = 'видео: ' + str(d['info_dict'].get('title', ''))
        o = base(); o.update(format='bv*+ba/b', merge_output_format='mp4', noplaylist=True, ignoreerrors=True, progress_hooks=[hk],
                             outtmpl=str(out / '_videos' / '%(title).80B [%(id)s].%(ext)s'))
        with yt_dlp.YoutubeDL(o) as y: i = y.extract_info(u, download=True)
        for e in ([x for x in i.get('entries', []) if x] if (i or {}).get('_type') == 'playlist' else [i] if i else []):
            p = (e.get('requested_downloads') or [{}])[0].get('filepath') or e.get('filepath')
            if p and os.path.exists(p):
                vids[u].append(Path(p)); add(e.get('title'), urlparse(job['url']).netloc, job['topic'] or 'Сайты', 'video', p, e.get('webpage_url') or u)
    except Exception: pass
    return vids[u]

def crawl(job):
    start = job['url']; h = urlparse(start).netloc; out = root('Sites') / safe(h); t0 = time.time()
    sel = list(job.get('sel') or []); cap = len(sel) or int(job.get('maxp') or 100)
    seen, qd, n, first, title, tot, vids, vloc, lim, cover = set(), set(sel or [start]), 0, None, h, [0], {}, {}, [False], ''
    pages = [(u, 0) for u in sel] if sel else [(start, 0)]
    def lp(u):
        p = urlparse(u); path = unquote(p.path) or '/'
        if path.endswith('/'): path += 'index.html'
        elif '.' not in path.rsplit('/', 1)[-1]: path += '/index.html'
        if p.query: path = re.sub(r'(\.\w+)$', '_' + re.sub(r'\W', '', p.query)[:20] + r'\1', path)
        return out / safe(p.netloc) / Path(*[safe(x) for x in path.strip('/').split('/')])
    def rel(u, cur): return os.path.relpath(lp(u), cur.parent).replace(os.sep, '/')
    def relp(p, cur): return os.path.relpath(p, cur.parent).replace(os.sep, '/')
    def save(u, data):
        f = lp(u); f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(data); tot[0] += len(data); job['speed'] = tot[0] / max(1, time.time() - t0)
    def css(s, base_):
        def r(m):
            u = urljoin(base_, m.group(2))
            if not u.startswith('http'): return m.group(0)
            asset(u); return 'url(%s%s%s)' % (m.group(1), rel(u, lp(base_)), m.group(1))
        return re.sub(r'url\((["\']?)(.*?)\1\)', r, s)
    apool = ThreadPoolExecutor(8); futs = []; slk = threading.Lock()
    def _asset(u):
        try:
            d, t = fetch(u)
            if 'css' in t: d = css(d.decode('utf-8', 'ignore'), u).encode()
            save(u, d)
        except Exception: pass
    def asset(u):  # картинки, стили и скрипты страницы качаются параллельно
        with slk:
            if u in seen or job['cancel']: return
            seen.add(u)
        futs.append(apool.submit(_asset, u))
    def vtarget(a):
        if a not in vloc:
            vloc[a] = None
            try:
                if a.split('?')[0].lower().endswith(('.m3u8', '.mpd')):
                    ps = grab(job, a, out, vids); vloc[a] = ps[0] if ps else None
                else: stream(job, a, lp(a), tot, t0); vloc[a] = lp(a)
            except Exception: pass
        return vloc[a]
    while pages and n < cap and not job['cancel']:
        u, d = pages.pop(0)
        if u in seen: continue
        seen.add(u)
        try: data, t = fetch(u)
        except Exception: continue
        if 'html' not in t: save(u, data); continue
        n += 1; job['title'] = f'{h}: страниц {n} из {cap}'; job['pct'] = min(99, n * 100 // cap); cur = lp(u); html = data.decode('utf-8', 'ignore')
        if first is None:
            first = cur; m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I); title = (m and m.group(1).strip()) or h
            # обложка: og:image, иначе первая картинка страницы (слева на странице тайтла)
            cm = (re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\'](.*?)["\']', html, re.I)
                  or re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']', html, re.I)
                  or re.search(r'<img\b[^>]*?\bsrc=["\'](.*?)["\']', html, re.I))
            if cm:
                try:
                    ca = urljoin(u, cm.group(1)); cd, ct = fetch(ca); cp = out / ('_cover' + (Path(urlparse(ca).path).suffix or '.jpg'))
                    if 'image' in ct: cp.parent.mkdir(parents=True, exist_ok=True); cp.write_bytes(cd); cover = str(cp)
                except Exception: pass
        def sub(m):
            tag, val = m.group(1).lower(), m.group(3)
            if val.startswith(('#', 'data:', 'mailto:', 'javascript:')) or tag == 'iframe': return m.group(0)
            a = urljoin(u, val).split('#')[0]
            if not a.startswith('http'): return m.group(0)
            if a.split('?')[0].lower().endswith(VEXT):
                t_ = vtarget(a) if job.get('videos', True) else None
                return m.group(0).replace(val, relp(t_, cur)) if t_ else m.group(0)
            if tag == 'a':
                if sel: return m.group(0).replace(val, rel(a, cur)) if a in qd else m.group(0)
                if urlparse(a).netloc != h or d >= job['depth'] or SKIP.search(a): return m.group(0)
                if a not in qd:
                    if len(qd) >= cap: lim[0] = True; return m.group(0)
                    qd.add(a); pages.append((a, d + 1))
            else: asset(a)
            return m.group(0).replace(val, rel(a, cur))
        html = re.sub(r'<(\w+)\b[^>]*?\b(?:src|href)=(["\'])(.*?)\2', sub, html)
        if job.get('videos', True):  # встроенные плееры (iframe) -> локальный <video>
            def fr(m):
                a = urljoin(u, m.group(2))
                if not VH.search(a): return m.group(0)
                return ''.join('<video controls preload="metadata" style="max-width:100%%" src="%s"></video>' % relp(p, cur) for p in grab(job, a, out, vids)) or m.group(0)
            html = re.sub(r'<iframe\b[^>]*?\bsrc=(["\'])(.*?)\1[^>]*>(?:\s*</iframe>)?', fr, html, flags=re.I | re.S)
        save(u, html.encode())
    while futs: futs.pop().result()
    apool.shutdown()
    if first:
        add(title, h, job['topic'] or 'Сайты', 'site', first, start, out, cover)
        if lim[0]: job['final'] = f'сохранено частично: достигнут лимит ({cap} стр.)'

def discover(tok, d):  # быстрый обход для визуального выбора страниц (только HTML, без картинок и видео)
    p = prev[tok]; start = d['urls'].split()[0]; h = urlparse(start).netloc; seen, level = {start}, [start]
    def get(u):
        try:
            data, t = fetch(u)
            if 'html' not in t: return u, None, []
            html = data.decode('utf-8', 'ignore'); m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
            ls = [urljoin(u, x).split('#')[0] for x in re.findall(r'<a\b[^>]*?\bhref=["\'](.*?)["\']', html, re.I)]
            return u, (m.group(1).strip() if m else u), [x for x in ls if x.startswith('http') and urlparse(x).netloc == h and not SKIP.search(x)]
        except Exception: return u, None, []
    for dep in range(int(d.get('depth', cfg['depth'])) + 1):
        nxt = []
        with ThreadPoolExecutor(6) as ex:
            for u, t, ls in ex.map(get, level):
                if t is None or len(p['pages']) >= 500: continue
                p['pages'].append({'url': u, 'title': t, 'depth': dep}); p['done'] = p['total'] = len(p['pages'])
                for x in ls:
                    if x not in seen: seen.add(x); nxt.append(x)
        level = nxt
        if not level or len(p['pages']) >= 500: break
    p['finished'] = True

# ---------- манга Senkuro: приём глав от закладки в браузере, загрузка страниц, читалка ----------
MH = ('shiro.senkuro.net', 'mirai.senkuro.net'); mlock = threading.Lock()
def sniff(b):
    if b[:3] == b'\xff\xd8\xff': return 'jpg'
    if b[:8] == b'\x89PNG\r\n\x1a\n': return 'png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return 'webp'
    if b[:6] in (b'GIF87a', b'GIF89a'): return 'gif'
    if b[4:12] in (b'ftypavif', b'ftypavis'): return 'avif'
def orig(u):  # ссылка shiro содержит адрес оригинала на mirai
    try:
        t = urlparse(u).path.rsplit('/', 1)[-1].split('.')[0]; o = base64.urlsafe_b64decode(t + '=' * (-len(t) % 4)).decode()
        return o if urlparse(o).hostname == 'mirai.senkuro.net' else ''
    except Exception: return ''
def img(u):  # через закладку: сначала оригинал, иначе то, что показал сайт
    for x in [orig(u), u]:
        if not x: continue
        try:
            guard(x)
            with opener().open(urllib.request.Request(x, headers={**UA, 'Referer': 'https://senkuro.me/'}), timeout=30) as r: d = r.read()
            if sniff(d): return d
        except Exception: pass
_sl = threading.Lock()
def speed_add(job, nb):  # скорость за последние 5 секунд для карточки загрузки
    now = time.time()
    with _sl:
        w = job.setdefault('_w', []); w.append((now, nb))
        while w and now - w[0][0] > 5: w.pop(0)
        job['speed'] = sum(x[1] for x in w) / max(1.0, now - w[0][0]); job['_ts'] = now
class Fast:  # параллельные скачивания картинок: соединения переиспользуются, cookie и User-Agent берутся у браузера
    def __init__(self, ua, cookies, site=None): self.ua, self.ck, self.loc, self.site = ua, cookies, threading.local(), site or SITE
    def get(self, u):
        for x in [orig(u), u]:
            p = urlparse(x or '')
            if not x or not manga_img_host(p.hostname): continue
            hdr = {'User-Agent': self.ua, 'Referer': self.site + '/', 'Accept': 'image/*,*/*', 'Cookie': '; '.join(f"{c['name']}={c['value']}" for c in self.ck if p.hostname.endswith(c['domain'].lstrip('.')))}
            if not hdr['Cookie']: del hdr['Cookie']
            d = self.loc.__dict__.setdefault('d', {}); k = (p.scheme, p.netloc)
            for _ in range(2):
                try:
                    if k not in d: d[k] = (http.client.HTTPSConnection if p.scheme == 'https' else http.client.HTTPConnection)(p.netloc, timeout=30)
                    d[k].request('GET', p.path + ('?' + p.query if p.query else ''), headers=hdr); r = d[k].getresponse(); b = r.read()
                    if r.status == 200 and sniff(b): return b
                    break
                except Exception:
                    try: d.pop(k).close()
                    except Exception: pass
def manga_chapter(job, d, get, tick=None, workers=1):  # качает страницы главы (workers>1 — параллельно), обновляет manifest и библиотеку
    folder = root('Manga') / safe(d['title'])[:60]; folder.mkdir(parents=True, exist_ok=True); mf = folder / 'manifest.json'; cover = ''; files = []; pages = d.get('pages') or []; n = len(pages)
    if d.get('cover'):
        b = get(d['cover'])
        if b: cp = folder / ('cover.' + sniff(b)); cp.write_bytes(b); cover = str(cp)
    if n:
        cd = folder / 'chapters' / d['cid']; cd.mkdir(parents=True, exist_ok=True); todo = []
        for i, u in enumerate(pages, 1):
            ex = next(cd.glob(f'{i:03d}.*'), None)
            if ex: files.append(ex.name)
            else: todo.append((i, u))
        def one(t):
            i, u = t
            if job['cancel']: return None
            b = get(u)
            if not b: return None
            fn = f'{i:03d}.{sniff(b)}'; (cd / fn).write_bytes(b); speed_add(job, len(b)); return fn
        pool = ThreadPoolExecutor(workers) if workers > 1 else None; k = n - len(todo)
        try:
            for fn in (pool.map(one, todo) if pool else map(one, todo)):
                k += 1
                if fn: files.append(fn)
                if tick: tick(k, n)
                else: job['title'] = f"{d['title']}: {d['label']} {k}/{n}"; job['pct'] = k * 100 // n
        finally:
            if pool: pool.shutdown()
        files.sort()
    with mlock:
        man = json.loads(mf.read_text('utf-8')) if mf.exists() else {'slug': d['slug'], 'title': d['title'], 'cover': '', 'chapters': {}}
        if n and files: man['chapters'][d['cid']] = {'label': d['label'], 'expected': d.get('expected') or n, 'files': files, 'done': len(files) == n == (d.get('expected') or n)}
        if d.get('listed'): man['listed'] = d['listed']
        if d.get('meta'): man['meta'] = d['meta']   # теги, автор, перевод, описание: показываются на карточке
        if d.get('source'): man['source'] = d['source']   # адрес тайтла: по нему лента проверяет новые главы
        if cover: man['cover'] = cover
        elif not man['cover'] and files: man['cover'] = str(folder / 'chapters' / d['cid'] / files[0])  # запасная обложка, пока нет настоящей
        mf.write_text(json.dumps(man, ensure_ascii=False), 'utf-8')
        add(d['title'], d.get('site_name') or 'Senkuro', 'Манга', 'manga', folder, 'manga:' + d['slug'], folder, man['cover'])
    ok = len(files) == n
    if n and not ok and not tick: job['final'] = f"частично: {len(files)} из {n} стр."
    return ok
def manga(job): manga_chapter(job, job['m'], img)  # приём от закладки (запасной способ)

def pw_get(ctx, site=None):  # запасной путь: скачивание средствами браузера (те же cookie и заголовки, что у сайта)
    def get(u):
        for x in [orig(u), u]:
            if not x: continue
            try:
                r = ctx.request.get(x, headers={'Referer': (site or SITE) + '/'}, timeout=30000)
                if r.ok:
                    b = r.body()
                    if sniff(b): return b
            except Exception: pass
    return get
TMO = 45000; TRIES = 2; ADS = re.compile(r'yandex\.|doubleclick|googlesyndication|googletagmanager|google-analytics|adfox', re.I)
SRC_OK = "()=>{const i=document.querySelector('.reader-item img');return !!i&&/^https?:/.test(i.src)}"
def pw_pages(pg, url, st):  # адреса всех страниц главы; режимы «Лента» и «По страницам»
    pg.goto(url, wait_until='domcontentloaded'); pg.wait_for_selector('.reader-item img', timeout=TMO)
    if pg.locator('.reader-main-vertical').count():  # быстрая прокрутка к первой ещё не загруженной странице
        pg.evaluate("""async()=>{const ok=()=>[...document.querySelectorAll('.reader-item img')].every(i=>/^https?:/.test(i.src));
          for(let k=0;k<400&&!ok();k++){for(const e of document.querySelectorAll('.reader-item')){if(!/^https?:/.test(e.querySelector('img').src)){e.scrollIntoView();break}}await new Promise(r=>setTimeout(r,80))}}""")
        pg.wait_for_function("()=>[...document.querySelectorAll('.reader-item img')].every(i=>/^https?:/.test(i.src))", timeout=TMO)
        return pg.eval_on_selector_all('.reader-item img', 'els=>els.map(i=>i.src)')
    m = re.search(r'/\s*(\d+)', pg.locator('.nav-panel__page span').first.inner_text()); total = int(m.group(1)) if m else 1
    pg.wait_for_function(SRC_OK, timeout=TMO); out = [pg.eval_on_selector('.reader-item img', 'i=>i.src')]
    for k in range(2, total + 1):
        try:  # листаем кликом без перезагрузки страницы; если не вышло — переходом по адресу (и больше клик не пробуем)
            if st.get('noclick'): raise RuntimeError('клик отключён')
            pg.click('.tap-zone__next', timeout=1500)
            pg.wait_for_function("p=>{const i=document.querySelector('.reader-item img');return !!i&&/^https?:/.test(i.src)&&i.src!==p}", arg=out[-1], timeout=6000)
        except Exception:
            st['noclick'] = True
            pg.goto(re.sub(r'/pages/\d+', f'/pages/{k}', url), wait_until='domcontentloaded'); pg.wait_for_function(SRC_OK, timeout=TMO)
        out.append(pg.eval_on_selector('.reader-item img', 'i=>i.src'))
    if len(set(out)) != len(out): raise RuntimeError('страницы не сменились (одинаковые картинки)')
    return out

SITE = os.environ.get('MEDIAHUB_SITE', 'https://senkuro.me')
# Списки сайтов (манга, видео, аудио, игры) живут в sites.json; расширение получает их через tools/gen_sites.py. Зеркала можно добавить переменными окружения.
import sites as siteprofiles, engine_mangabuff, engine_nudemoon, engine_games, enginekit, lan, feedlib
from http.cookies import SimpleCookie
SESS, THR, LAN_BOUND = lan.Sessions(), lan.Throttle(), False   # доступ с других устройств (lan.py): сессии, защита от подбора PIN, слушает ли сервер всю сеть
def cfg_public(): return {k: v for k, v in cfg.items() if k not in ('lan_pin_salt', 'lan_pin_hash')} | {'lan_pin_set': bool(cfg.get('lan_pin_hash'))}   # хэш PIN никому не отдаём
SITES = siteprofiles.with_extra_manga(siteprofiles.load(), [urlparse(SITE).hostname or 'senkuro.me'] + os.environ.get('MEDIAHUB_MANGA_HOSTS', '').split(','))
MANGA_HOSTS = siteprofiles.manga_hosts(SITES)
def manga_url(url): return siteprofiles.manga_title(SITES, url)   # ссылка на тайтл -> (адрес сайта, slug) или None; сайт берётся из самой ссылки
def manga_img_host(h): return siteprofiles.manga_img_host_ok(SITES, h)   # откуда можно брать картинки: сам сайт, его родительский домен и CDN из профиля
NO_MANGA = 'ссылка должна вести на тайтл манги: ' + ', '.join(MANGA_HOSTS)
def chapter_done(folder, cid):
    try: return bool(json.loads((folder / 'manifest.json').read_text('utf-8'))['chapters'].get(cid, {}).get('done'))
    except Exception: return False
def joblog(folder, text):
    try:
        with open(folder / 'download.log', 'a', encoding='utf-8') as f: f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
    except Exception: pass
def manga_site(job):  # ссылка на тайтл -> сами открываем сайт в Edge/Chrome; страницы качаются параллельно, пока браузер листает следующую главу
    try: from playwright.sync_api import sync_playwright
    except ImportError: raise RuntimeError('нужен playwright: запустите start.bat ещё раз')
    mt = manga_url(job['url'])
    if not mt: raise RuntimeError(NO_MANGA)
    site, slug = mt; bad = {}; okn = [0]; N = 0; warn = ''
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(BASE / 'browser_profile'), headless=not cfg.get('show_browser'), viewport={'width': 1100, 'height': 900}, **({} if cfg.get('browser') in ('', 'chromium') else {'channel': cfg.get('browser') or 'msedge'}))
        try:
            ck = browser_cookies(urlparse(site).hostname or 'senkuro.me')
            if ck: ctx.add_cookies(ck)
        except Exception as e: warn = f' Cookie из браузера не взяты: {str(e)[:160]}'
        blk = [True]
        def block(route):  # картинки и реклама браузеру не нужны: адреса страниц берём из разметки, сами картинки качаем отдельно
            r = route.request
            if blk[0] and (r.resource_type in ('image', 'media', 'font') or ADS.search(urlparse(r.url).hostname or '')): return route.abort()
            route.continue_()
        ctx.route('**/*', block); pool = ThreadPoolExecutor(3)
        try:
            pg = ctx.new_page(); job['title'] = 'открываю страницу тайтла…'
            pg.goto(f'{site}/manga/{slug}/chapters', wait_until='domcontentloaded')
            try: pg.wait_for_selector('article.card-chapter', timeout=TMO)
            except Exception: raise RuntimeError('список глав не открылся (капча или блокировка?). Включите в настройках «Показывать окно браузера» и повторите')
            exp = 0
            try: mm = re.search(r'Главы\s+(\d+)', pg.inner_text('body')); exp = int(mm.group(1)) if mm else 0
            except Exception: pass
            last, calm = -1, 0
            for _ in range(80):  # список глав подгружается постепенно: ждём, пока он перестанет расти
                c = pg.locator('article.card-chapter').count(); job['title'] = f'ищу главы… найдено {c}' + (f' из {exp}' if exp else '')
                calm = calm + 1 if c == last else 0; last = c
                if calm >= (2 if exp and c >= exp else 6) or job['cancel']: break
                try: pg.locator('article.card-chapter').last.scroll_into_view_if_needed(timeout=2000)
                except Exception: pass
                pg.keyboard.press('End'); pg.mouse.wheel(0, 30000)
                try: pg.get_by_role('button', name=re.compile(r'^(показать|загрузить)\s+ещ[её]', re.I)).first.click(timeout=500)
                except Exception: pass
                pg.wait_for_timeout(900)
            title = pg.locator('h1').first.inner_text().strip() or slug; po = pg.locator('.project-poster img').first
            cover = urljoin(pg.url, po.get_attribute('data-zoom-src') or po.get_attribute('src') or '') if po.count() else ''
            chs = pg.eval_on_selector_all('article.card-chapter', "els=>els.map(a=>({url:(a.querySelector('a.card-chapter__link')||a.querySelector('a')).href,label:((a.querySelector('.card-chapter__name')||a).textContent||'').trim()}))")
            for c in chs: mm = re.search(r'chapters/(\d+)', c['url']); c['cid'] = mm.group(1) if mm else ''
            chs = [c for c in chs if c['cid']][::-1]  # от первой главы к последней
            if not chs: raise RuntimeError('главы не найдены')
            if exp and len(chs) < exp - 1: warn = f' Найдено глав {len(chs)}, а на сайте указано {exp}: повторите загрузку.'
            slow = pw_get(ctx, site); fast = Fast(pg.evaluate('navigator.userAgent'), ctx.cookies(), site); folder = root('Manga') / safe(title)[:60]
            manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': cover, 'listed': [{'cid': c['cid'], 'label': c['label']} for c in chs]}, slow)
            pst = {}; sel = chs[(job.get('first') or 1) - 1:(job.get('last') or len(chs))]; N = len(sel); pending, retry, fin, t0 = [], [], [0], time.time(); noop = lambda k, n: None
            def reap(keep):  # забираем завершённые скачивания; keep — сколько можно оставить в работе
                while pending and (len(pending) > keep or pending[0][0].done()):
                    f, c, d = pending.pop(0)
                    try: ok = f.result()
                    except Exception: ok = False
                    if ok: okn[0] += 1; fin[0] += 1; joblog(folder, c['label'] + ': ok')
                    else: retry.append((c, d))
                job['pct'] = min(99, int((fin[0] + len(retry)) * 100 / N))
            for i, c in enumerate(sel, 1):
                if job['cancel']: break
                job['title'] = f"{title} · глава {i}/{N} · {c['label']}" + (f' · качается {len(pending)}' if pending else ''); job['eta'] = int((time.time() - t0) / i * (N - i))
                if chapter_done(folder, c['cid']): okn[0] += 1; fin[0] += 1; continue  # уже скачана раньше
                err, pages = '', None
                for att in range(TRIES):
                    blk[0] = att == 0  # вторая попытка — без блокировки картинок
                    try: pages = pw_pages(pg, c['url'], pst); break
                    except Exception as e: err = (str(e).splitlines() or [repr(e)])[0][:160]
                blk[0] = True
                if not pages: bad[c['label']] = err; fin[0] += 1; joblog(folder, f"{c['label']}: {err}"); continue
                d = {'slug': slug, 'cid': c['cid'], 'title': title, 'label': c['label'], 'expected': len(pages), 'pages': pages}
                pending.append((pool.submit(manga_chapter, job, d, fast.get, noop, 8), c, d)); reap(2)
            reap(0)
            for c, d in retry:  # запасной проход: недокачанное берём средствами браузера
                if job['cancel']: break
                job['title'] = f"{title} · повторная загрузка · {c['label']}"
                if manga_chapter(job, d, slow, noop): okn[0] += 1; joblog(folder, c['label'] + ': ok (повтор)')
                else: bad[c['label']] = 'не все страницы скачались'; joblog(folder, c['label'] + ': не все страницы скачались')
        finally:
            pool.shutdown(); ctx.close()
    job['final'] = (f'готово: {okn[0]} из {N} глав.' if not bad else f'частично: {okn[0]} из {N} глав. Не удалось: ' + '; '.join(f'{k} ({v})' for k, v in list(bad.items())[:3])) + warn

MB_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
def http_html(url):  # страница сайта без расширения: обычный запрос; cookie берутся из браузера, если он выбран в настройках
    guard(url); host = urlparse(url).hostname or ''; hdr = {'User-Agent': MB_UA, 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8', 'Accept-Language': 'ru,en;q=0.8', 'Referer': f'https://{host}/'}
    try: ck = '; '.join(f"{c['name']}={c['value']}" for c in browser_cookies(host))
    except Exception: ck = ''
    if ck: hdr['Cookie'] = ck
    try:
        with opener().open(urllib.request.Request(url, headers=hdr), timeout=30) as r: return enginekit.decode_html(r.read(3_000_000), r.headers.get_content_charset() or '')   # кодировку называет заголовок ответа (у старых сайтов windows-1251)
    except urllib.error.HTTPError as e: return enginekit.decode_html(e.read(200_000), e.headers.get_content_charset() or '')   # заглушка проверки браузера приходит с кодом 403/503: пусть её опознает движок
def html_source(job):  # откуда брать HTML страниц: расширение (ваш вход, проверка «я не робот» проходит само) или прямой запрос
    v = cfg.get('manga_via', 'auto'); via_ext = v == 'browser' or (v == 'auto' and ext_online())
    def get_html(url):
        if job['cancel']: raise RuntimeError('отменено')
        if via_ext: return fetch_html(url, job)
        time.sleep(0.4); return http_html(url)   # без расширения не частим
    return get_html
def manga_nudemoon(job):  # Nude-Moon: глав нет, весь комикс = одна «глава»; страницы и теги берутся с самой страницы комикса
    mt = manga_url(job['url']); prof = siteprofiles.manga_profile(SITES, job['url'])
    if not mt or not prof: raise RuntimeError(NO_MANGA)
    site, slug = mt; name = prof.get('name') or 'Nude-Moon'; job['title'] = 'открываю страницу комикса…'
    try: c = engine_nudemoon.load_comic(html_source(job), job['url'])
    except enginekit.EngineError as e: raise RuntimeError(str(e))
    title = c['title']; folder = root('Manga') / safe(title)[:60]; fast = Fast(MB_UA, [], site)
    meta = {k: c[k] for k in ('tags', 'authors', 'translators', 'description', 'date', 'source')}
    manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': c['cover'], 'listed': [{'cid': '1', 'label': 'Целиком'}], 'site_name': name, 'meta': meta}, fast.get)
    if chapter_done(folder, '1'): job['final'] = 'уже скачано'; return
    d = {'slug': slug, 'cid': '1', 'title': title, 'label': 'Целиком', 'expected': len(c['pages']), 'pages': c['pages'], 'site_name': name}
    if manga_chapter(job, d, fast.get, None, 8): joblog(folder, 'ok'); job['final'] = f"готово: {len(c['pages'])} стр." + (' ' + c['warn'] if c['warn'] else '')
    else: joblog(folder, job.get('final') or 'не все страницы скачались')
def manga_http(job):  # сайты со «обычной» разметкой (engine в sites.json): HTML тайтла и глав через расширение или напрямую, картинки по адресам из разметки
    mt = manga_url(job['url']); prof = siteprofiles.manga_profile(SITES, job['url'])
    if not mt or not prof: raise RuntimeError(NO_MANGA)
    site, slug = mt; name = prof.get('name') or 'Манга'; get_html = html_source(job)
    job['title'] = 'открываю страницу тайтла…'
    try: t = engine_mangabuff.load_title(get_html, site, slug)
    except engine_mangabuff.EngineError as e: raise RuntimeError(str(e))
    title = t['title'] or slug; chs = t['chapters'][::-1]; folder = root('Manga') / safe(title)[:60]; fast = Fast(MB_UA, [], site); noop = lambda k, n: None   # от первой главы к последней
    manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': t['cover'], 'listed': [{'cid': c['cid'], 'label': c['label']} for c in chs], 'site_name': name, 'source': f'{site}/manga/{slug}'}, fast.get)
    sel = chs[(job.get('first') or 1) - 1:(job.get('last') or len(chs))]; N = len(sel); okn = 0; bad = {}; t0 = time.time()
    for i, c in enumerate(sel, 1):
        if job['cancel']: break
        job['title'] = f"{title} · глава {i}/{N} · {c['label']}"; job['eta'] = int((time.time() - t0) / i * (N - i)); job['pct'] = min(99, (i - 1) * 100 // max(1, N))
        if chapter_done(folder, c['cid']): okn += 1; continue   # уже скачана раньше
        err, pages = '', None
        for att in range(TRIES):
            try: pages = engine_mangabuff.load_pages(get_html, c); break
            except Exception as e:
                err = (str(e).splitlines() or [repr(e)])[0][:160]
                if job['cancel']: break
                time.sleep(1.5)
        if not pages: bad[c['label']] = err; joblog(folder, f"{c['label']}: {err}"); continue
        d = {'slug': slug, 'cid': c['cid'], 'title': title, 'label': c['label'], 'expected': len(pages), 'pages': pages, 'site_name': name}
        if manga_chapter(job, d, fast.get, noop, 8): okn += 1; joblog(folder, c['label'] + ': ok')
        else: bad[c['label']] = 'не все страницы скачались'; joblog(folder, c['label'] + ': не все страницы скачались')
    job['final'] = f'готово: {okn} из {N} глав.' if not bad else f'частично: {okn} из {N} глав. Не удалось: ' + '; '.join(f'{k} ({x})' for k, x in list(bad.items())[:3])
def by_engine(default):  # у каждого сайта манги свой способ загрузки (engine в sites.json); senkuro остаётся на прежнем пути
    def run(job):
        p = siteprofiles.manga_profile(SITES, job['url'])
        return {'mangabuff': manga_http, 'nudemoon': manga_nudemoon}.get(siteprofiles.engine_of(p), default)(job)
    return run
_gs = {}
def games_store():  # GameSweep живёт внутри MediaHub без своего сервера; после каждого сканирования игры попадают в библиотеку
    if 'st' not in _gs:
        import sys; sys.path.insert(0, str(BASE)); import gamesweep
        _gs['st'] = gamesweep.Store(cfg.get('games_root', '')); _gs['st'].on_done = sync_games
    return _gs['st']
def games_scan(root):
    if root and os.path.isdir(root): games_store().start_scan(root, 'auto')
def plural(n, f): return f'{n} ' + (f[0] if n % 10 == 1 and n % 100 != 11 else f[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else f[2])
def sync_games(games, root):  # установленные игры: сливаем с карточками из браузера (по названию), остальные добавляем
    import gamesweep
    root = os.path.abspath(root); buckets = {}
    for g in games:
        pn = gamesweep.parse_name(g['name']); buckets.setdefault(pn['key'] or g['name'].casefold(), []).append((g, pn))
    groups = {gr['key']: gr for gr in gamesweep.build_groups(games)}; touched = set(); pins = {}
    links = {r['path']: r['item_id'] for r in sql('select path,item_id from links')}; lmeth = {r['path']: r['method'] for r in sql('select path,method from links')}
    for r in sql("select * from items where kind='game'"):
        if ginfo(r).get('pin'): pins[os.path.abspath(ginfo(r)['pin'])] = r     # папка, которую вы привязали к карточке вручную
    for key, ms in buckets.items():
        gr = groups.get(key); keep = next((r for r in gr['members'] if r['status'] == 'оставить'), None) if gr else None
        pinned = next(((g, pins[os.path.abspath(g['path'])]) for g, _ in ms if os.path.abspath(g['path']) in pins), None)
        newest = pinned[0] if pinned else next((g for g, _ in ms if keep and g['path'] == keep['path']), None) or max((g for g, _ in ms), key=lambda g: g.get('mtime') or 0)
        pn = next(p for g, p in ms if g is newest); title = (gr['title'] if gr else ms[0][1]['base']) or ms[0][0]['name']; old = sum(1 for r in (gr['members'] if gr else []) if r['status'] in ('старая', 'дубль'))
        inst = {'version': (keep or {}).get('version') or (pn.get('text') or ''), 'versions': len(ms), 'old': old, 'root': root, 'path': newest['path']}
        via = 'manual' if pinned else 'name'; row = pinned[1] if pinned else find_game(key, title)
        if not row: row, via = card_by_memory(ms, links)
        info = ginfo(row) if row else {}; info['inst'] = inst; info.setdefault('added', time.time()); info.setdefault('auto', True)
        vs = [info.get('meta', {}).get('version', '')] + [s.get('version', '') for s in (info.get('sources') or {}).values()]; info['update'] = bool(inst['version'] and any(v and gamelib.newer(v, inst['version']) for v in vs))   # новее ли установленной любая из сборок
        if row:
            sql('update items set path=?, size=?, info=? where id=?', (newest['path'], int(newest.get('size') or 0), json.dumps(info, ensure_ascii=False), row['id'])); touched.add(row['id'])
        else:
            sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)", (title, Path(root).name or 'Игры', 'Игры', 'game', newest['path'], '', 'game:' + key, int(newest.get('size') or 0), '', root, json.dumps(info, ensure_ascii=False)))
            touched.add(sql('select id from items where url=?', ('game:' + key,))[0]['id']); via = 'name'
        rid = row['id'] if row else sql('select id from items where url=?', ('game:' + key,))[0]['id']
        for g, _ in ms:   # запоминаем «эта папка = эта карточка»; найденная по записи (link) остаётся с прежним способом
            ap = os.path.abspath(g['path'])
            if via != 'link' and (links.get(ap) != rid or lmeth.get(ap) != via): sql('insert or replace into links(path,item_id,method,at) values(?,?,?,?)', (ap, rid, via, time.time())); links[ap] = rid; lmeth[ap] = via
        thread = (info.get('meta') or {}).get('thread') or ''
        if cfg.get('game_marker', True) and (thread or pinned):   # маркер только для карточек с темой или ручной привязкой: у остальных ключ и так следует из названия папки
            card = {'thread': thread, 'key': (row['url'][5:] if row and str(row['url']).startswith('game:') else name_key(row['title'] if row else title)), 'title': row['title'] if row else title}
            for g, p_ in ms:
                if g.get('type') == 'folder': gamelink.write_marker(g['path'], dict(card, version=p_.get('text') or ''), 'manual' if pinned and g is pinned[0] else 'auto', g.get('mtime') or 0)
    for r in sql("select * from items where kind='game'"):
        i = ginfo(r)
        if r['id'] in touched or i.get('inst', {}).get('root') != root and r['src'] != root: continue
        if i.get('meta'): i.pop('inst', None); sql("update items set path='', size=0, info=? where id=?", (json.dumps(i, ensure_ascii=False), r['id']))   # карточка остаётся, игра больше не скачана
        else: sql('delete from items where id=?', (r['id'],))
def manga_extra(r):
    if r['kind'] == 'game':
        g = game_view(r); return ' · '.join(x for x in [g['version'] or (g['latest'] if not g['downloaded'] else ''), ('старых ' + str(g['old'])) if g['old'] else ''] if x)
    if r['kind'] != 'manga': return ''
    try: m = json.loads((Path(r['root']) / 'manifest.json').read_text('utf-8')); tg = ', '.join((m.get('meta') or {}).get('tags', [])[:3]); return f"{len(m['chapters'])} из {len(m.get('listed', [])) or '?'} гл." + (' · ' + tg if tg else '')
    except Exception: return ''

def manga_info(i):
    r = sql('select * from items where id=? and kind=?', (i, 'manga'))
    if not r: return {'error': 'not found'}
    man = json.loads((Path(r[0]['root']) / 'manifest.json').read_text('utf-8')); pr = sql('select cid,page from progress where slug=?', (man['slug'],))
    allc = {c['cid']: {'id': c['cid'], 'label': c['label'], 'files': [], 'expected': 0, 'done': False} for c in man.get('listed', [])}
    for k, v in man['chapters'].items(): allc[k] = dict(v, id=k)
    chs = sorted(allc.values(), key=lambda c: [float(x) for x in re.findall(r'\d+(?:\.\d+)?', c['label'])] or [0])
    return {'title': man['title'], 'chapters': chs, 'total': len(man.get('listed', [])), 'have': len(man['chapters']), 'progress': dict(pr[0]) if pr else None, 'meta': man.get('meta') or {}}

# ---------- оценка размера ----------
def preview(tok, d):
    import yt_dlp
    p = prev[tok]; kind = d['kind']
    if kind in ('site', 'mangaurl'): p['err'].append('Для сайтов размер заранее неизвестен'); p['finished'] = True; return
    o = base(); o.update(format=fmt(kind, d.get('res') or cfg['res']), extract_flat='in_playlist', ignoreerrors=True, skip_download=True)
    af = BASE / f'archive_{kind}.txt'; arch = set(af.read_text('utf-8').splitlines()) if cfg['skip'] and af.exists() else set()
    def size(i):
        return int(sum(f.get('filesize') or f.get('filesize_approx') or (f.get('tbr') or 0) * 125 * (i.get('duration') or 0) for f in (i.get('requested_formats') or [i])))
    def one(e):
        if (str(e.get('ie_key') or e.get('extractor_key') or '').lower() + ' ' + str(e.get('id'))) in arch: return -1
        try:
            if e.get('formats') or e.get('requested_formats'): return size(e)
            with yt_dlp.YoutubeDL(dict(o, extract_flat=False, noplaylist=True)) as y: return size(y.extract_info(e.get('url') or e.get('webpage_url'), download=False))
        except Exception: return 0
    for u in [x.strip() for x in d['urls'].splitlines() if x.strip().startswith('http')]:
        try:
            with yt_dlp.YoutubeDL(o) as y: t = y.extract_info(u, download=False)
            ents = [e for e in t['entries'] if e] if t.get('_type') == 'playlist' else [t]
        except Exception as ex: p['err'].append(str(ex)[:100]); continue
        p['total'] += len(ents)
        with ThreadPoolExecutor(4) as ex:
            for s in ex.map(one, ents):
                p['done'] += 1
                if s < 0: p['skipped'] += 1
                elif s == 0: p['unknown'] += 1
                else: p['size'] += s
    p['finished'] = True

# ---------- очередь / расписание ----------
def enqueue(j):
    jobs[j['id']] = j
    if j['start_at'] > time.time():
        j['status'] = 'запланировано ' + datetime.fromtimestamp(j['start_at']).strftime('%d.%m %H:%M')
        t = threading.Timer(j['start_at'] - time.time(), fire, (j,)); t.daemon = True; t.start()
    else: Q.put(j)
def fire(j):
    if j['cancel']: return
    j['status'] = 'в очереди'; Q.put(j)
    if j['daily']: enqueue(dict(j, id=next(ids), start_at=j['start_at'] + 86400, cancel=False, pct=0, speed=0))
_wk = [0]
def spawn_workers():
    cfg['workers'] = max(1, min(12, int(cfg.get('workers') or 3)))
    while _wk[0] < cfg['workers']: threading.Thread(target=worker, daemon=True).start(); _wk[0] += 1
def worker():
    while True:
        j = Q.get()
        if j['cancel']: j['status'] = 'отменено'; continue
        j['status'] = 'качается'
        try: ({'site': crawl, 'manga': manga, 'mangaurl': by_engine(manga_site), 'mangabrowser': by_engine(manga_browser), 'gamecard': game_card, 'gamecheck': game_check, 'gamereplace': game_replace, 'feedcheck': feed_check}.get(j['kind'], media))(j); j['status'] = 'отменено' if j['cancel'] else j.pop('final', 'готово'); j['pct'] = 100
        except Exception as e: j['status'] = 'отменено' if j['cancel'] else 'ошибка: ' + str(e)[:150]
        j['speed'] = 0

# ---------- расширение браузера: входящие вкладки ----------
for c_ in ('src', 'tracked int default 0', 'checked', 'info'):
    try: db.execute('alter table items add column ' + c_)
    except sqlite3.OperationalError: pass
db.execute("create table if not exists inbox(id integer primary key, batch text, tab_id int, window_id int, url text, title text, kind text, host text, action text, state text, lib_id int, close_tab int, status text, reason text default '', jobs text default '[]', cmd text default '', created text default current_timestamp)")
EXTF = BASE / 'ext.json'
try: EXT = json.loads(EXTF.read_text('utf-8'))  # подключённые расширения: {origin: токен}
except Exception: EXT = {}
PAIR = {}  # запросы на подключение, ждущие решения человека
def ext_save(): EXTF.write_text(json.dumps(EXT, ensure_ascii=False), 'utf-8')
ACT = {'manga': ['download', 'track', 'link', 'skip'], 'video': ['download', 'link', 'skip'], 'playlist': ['download', 'track', 'link', 'skip'], 'audio': ['download', 'link', 'skip'],
       'podcast': ['link', 'track', 'skip'], 'game': ['gamecard', 'link', 'skip'], 'unknown': ['link', 'site', 'skip']}
DEFAULT = {'manga': 'download', 'video': 'download', 'playlist': 'download', 'audio': 'download', 'podcast': 'link', 'game': 'link', 'unknown': 'link'}
JOBK = {'manga': 'mangaurl', 'video': 'video', 'playlist': 'video', 'audio': 'audio', 'unknown': 'site'}
def classify(url):  # тип материала и ключ для поиска в библиотеке (по адресу, без запросов в сеть)
    u = urlparse(url); h = (u.hostname or '').lower(); h = h[4:] if h.startswith('www.') else h; q = parse_qs(u.query); p = u.path; r = {'kind': 'unknown', 'host': h, 'key': url}
    mg = manga_url(url)
    if mg: return dict(r, kind='manga', key='manga:' + mg[1], norm=siteprofiles.title_url(SITES, url))
    if h in ('youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'):
        vid = p.strip('/') if h == 'youtu.be' else (q.get('v') or [''])[0]; lst = (q.get('list') or [''])[0]
        if p == '/playlist' and lst: return dict(r, kind='playlist', key='https://www.youtube.com/playlist?list=' + lst)
        if p.startswith(('/@', '/channel/', '/c/', '/user/')): return dict(r, kind='playlist', key=url.split('?')[0].split('#')[0])
        if vid: return dict(r, kind='audio' if h == 'music.youtube.com' else 'video', key='https://www.youtube.com/watch?v=' + vid)
    sp = siteprofiles.match(SITES, h, p, ('video', 'audio'))
    if sp: return dict(r, kind=sp['kind'])
    if h == 'podcasts.apple.com' or (h == 'open.spotify.com' and p.startswith('/show')) or p.endswith(('.rss', '.xml')): return dict(r, kind='podcast')
    sp = siteprofiles.match(SITES, h, p, ('game',))
    if sp: return dict(r, kind='game', key=game_key(url)) if siteprofiles.engine_of(sp) != 'f95' or sp['id'] == 'f95zone' else dict(r, kind='game')
    return r
def new_job(url, kind, **kw):
    j = {'id': next(ids), 'url': url, 'kind': kind, 'res': cfg['res'], 'afmt': cfg['afmt'], 'depth': int(cfg['depth']), 'maxp': int(cfg['maxp']), 'videos': bool(cfg['videos']), 'sel': [], 'first': 0, 'last': 0,
         'topic': '', 'subs': cfg['subs_langs'] if cfg['subs_on'] else '', 'thumbs': bool(cfg['thumbs']), 'start_at': 0.0, 'daily': False, 'status': 'в очереди', 'pct': 0, 'title': url, 'speed': 0, 'eta': 0, 'cancel': False}
    j.update(kw); enqueue(j); return j['id']
def add_link(title, key, src, host, tracked=0):  # источник сохраняется в любом случае, даже если скачивание не выбрано
    sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,tracked) values(?,?,?,?,?,?,?,?,?,?,?) on conflict(url) do update set src=excluded.src, tracked=max(coalesce(items.tracked,0), excluded.tracked)",
        (title or key, host, 'Ссылки', 'link', '', '', key, 0, '', src, tracked))
def inbox_add(tabs, close, browser, rest_as_site=False):
    batch = time.strftime('%Y%m%d%H%M%S') + '-' + str(next(ids)); seen = set(); n = 0
    for t in tabs[:200]:
        url = str(t.get('url') or '')[:2000]
        if not url.startswith(('http://', 'https://')): continue
        c = classify(url); key = c['key']; state, lib, action = 'new', None, ('gamecard' if c['host'] == 'f95zone.to' else 'site' if (rest_as_site and c['kind'] == 'unknown') else DEFAULT[c['kind']])
        if key in seen: state, action = 'dup', 'skip'
        else:
            seen.add(key); it = sql("select * from items where url=? or (kind='game' and src=?)", (key, key))
            if it:
                it = it[0]; lib = it['id']
                if it['kind'] == 'game': state = 'downloaded' if (it['path'] and Path(it['path']).exists()) else 'card'; action = 'known'
                elif it['kind'] == 'link': state = 'link'
                elif it['path'] and not Path(it['path']).exists(): state = 'missing'
                else: state = 'downloaded'; action = 'known' if c['kind'] != 'playlist' else action
        sql('insert into inbox(batch,tab_id,window_id,url,title,kind,host,action,state,lib_id,close_tab,status) values(?,?,?,?,?,?,?,?,?,?,?,?)',
            (batch, t.get('id'), t.get('windowId'), url, str(t.get('title') or url)[:300], c['kind'], c['host'], action, state, lib, 1 if close else 0, 'pending')); n += 1
    return batch, n
def finish_row(rid, close): sql('update inbox set status=?, cmd=? where id=?', ('closing', 'close', rid) if close else ('done', '', rid))
def inbox_confirm(d):  # человек подтвердил план: ссылки сохраняются, загрузки уходят в очередь, пропущенное остаётся как есть
    rows = {r['id']: r for r in sql('select * from inbox where batch=?', (d['batch'],))}; close = bool(d.get('close')); nd = nl = 0
    for x in d.get('rows', []):
        r = rows.get(x.get('id'))
        if not r or r['status'] != 'pending': continue
        kind = x.get('kind') if x.get('kind') in ACT else r['kind']; a = x.get('action'); a = a if (a in ACT[kind] or (a == 'known' and r['state'] in ('downloaded', 'card'))) else 'skip'
        sql('update inbox set kind=?, action=?, close_tab=? where id=?', (kind, a, 1 if close else 0, r['id']))
        if a == 'skip': sql("update inbox set status='skipped' where id=?", (r['id'],)); continue
        if a == 'known': finish_row(r['id'], close); continue
        c = classify(r['url'])
        if a == 'gamecard':
            jid = new_job(c['key'] or r['url'], 'gamecard', title=r['title']); sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), r['id'])); nd += 1; continue
        add_link(r['title'], c['key'], r['url'], r['host'], 1 if (a == 'track' or kind == 'playlist') else 0)
        if a in ('link', 'track'): finish_row(r['id'], close); nl += 1; continue
        jk = 'site' if a == 'site' else JOBK.get(kind)
        if jk == 'mangaurl': jk = manga_kind()
        if not jk: sql("update inbox set status='kept', reason=? where id=?", ('скачивание с этого источника пока недоступно', r['id'])); continue
        jid = new_job(c.get('norm') or r['url'], jk, title=r['title']); sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), r['id'])); nd += 1
    return {'download': nd, 'links': nl}
def settle():  # смотрим, чем закончились задания, и решаем судьбу вкладок: закрыть только после успеха
    for r in sql("select * from inbox where status='queued'"):
        js_ = json.loads(r['jobs'] or '[]'); sts = [jobs[j]['status'] for j in js_ if j in jobs]
        if len(sts) < len(js_):  # приложение перезапускалось: заданий в памяти нет, смотрим, что реально лежит в библиотеке
            it = sql('select * from items where url=?', (classify(r['url'])['key'],)); okn = bool(it and it[0]['kind'] != 'link' and Path(it[0]['path']).exists())
            sts = ['готово'] if okn else ['ошибка: загрузка не завершилась, добавьте её снова']
        if any(re.match(r'(качается|в очереди|запл)', s) for s in sts): continue
        bad = next((s for s in sts if not s.startswith(('готово', 'сохранено', 'пропущено'))), '')
        if not bad: finish_row(r['id'], r['close_tab']); continue
        low = bad.lower(); why = ('нужен вход на сайте' if re.search(r'login|sign in|private|authent|cookies|членам|вход', low) else 'скачано частично' if bad.startswith('частично') else 'загрузка отменена' if bad.startswith('отменено') else 'не удалось скачать (' + bad.replace('ошибка:', '').strip()[:120] + ')')
        sql("update inbox set status='kept', reason=? where id=?", (why, r['id']))
def settle_loop():
    while True:
        try: settle()
        except Exception: pass
        time.sleep(2)
def inbox_view(r):
    st = r['status']; act = r['action']
    st_txt = {'new': 'Новое', 'dup': 'Такая же вкладка уже есть в этом списке', 'link': 'Уже в библиотеке · только ссылка', 'missing': 'Уже в библиотеке · файл не найден', 'downloaded': 'Уже в библиотеке · скачано', 'card': 'Уже в библиотеке игр · не скачано'}.get(r['state'], '')
    fate = {'pending': 'Вкладка закроется после обработки' if (r['close_tab'] and act != 'skip') else 'Вкладка останется открытой', 'queued': 'Загружается' + (', вкладка закроется после завершения' if r['close_tab'] else ''),
            'closing': 'Закрываю вкладку…', 'closed': 'Вкладка закрыта · источник сохранён в библиотеке', 'done': 'Готово · источник сохранён в библиотеке', 'skipped': 'Пропущено, вкладка осталась открытой',
            'reopened': 'Вкладка возвращена', 'kept': 'Вкладка осталась открытой: ' + (r['reason'] or '')}.get(st, '')
    return {'id': r['id'], 'title': r['title'], 'url': r['url'], 'host': r['host'], 'kind': r['kind'], 'action': act, 'actions': ACT.get(r['kind'], []) + (['known'] if r['state'] in ('downloaded', 'card') else []),
            'state': r['state'], 'state_text': st_txt, 'status': st, 'fate': fate, 'close': bool(r['close_tab'])}
def inbox_state():
    out = []
    for b in sql('select batch, min(created) c, count(*) n from inbox group by batch order by batch desc limit 8'):
        rows = sql('select * from inbox where batch=? order by id', (b['batch'],)); out.append({'batch': b['batch'], 'created': b['c'], 'rows': [inbox_view(r) for r in rows], 'pending': any(r['status'] == 'pending' for r in rows)})
    return {'batches': out}

# ---------- задания для расширения: манга в браузере пользователя ----------
XT, XTL, EXT_SEEN = {}, threading.Lock(), [0.0]
def ext_online(): return bool(EXT) and time.time() - EXT_SEEN[0] < 40
def manga_kind():  # где качать мангу: в браузере пользователя (расширение) или отдельным окном (Playwright)
    v = cfg.get('manga_via', 'auto'); return 'mangabrowser' if v == 'browser' or (v == 'auto' and ext_online()) else 'mangaurl'
def take_tasks():
    with XTL:
        out = []
        for tid, t in XT.items():
            if not t['sent']: t['sent'] = True; out.append({'id': tid, 'type': t['type'], 'payload': t['payload']})
        return out
def xtask(kind, payload, timeout=180, job=None):  # поставить задание расширению и дождаться ответа
    tid = next(ids); ev = threading.Event(); end = time.time() + timeout
    with XTL: XT[tid] = {'type': kind, 'payload': payload, 'ev': ev, 'res': None, 'sent': False}
    try:
        while not ev.wait(1):
            if job and job['cancel']: raise RuntimeError('отменено')
            if time.time() > end: raise RuntimeError('расширение не ответило: откройте браузер с расширением MediaHub и не закрывайте окно загрузки')
        r = XT[tid]['res']
    finally:
        with XTL: XT.pop(tid, None)
    if not r.get('ok'): raise RuntimeError(r.get('error') or 'расширение вернуло ошибку')
    return r.get('data') or {}
def firefox_cookies(domain):  # cookie Firefox читаются спокойно и при открытом браузере
    import glob, tempfile
    roots = [os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles'), os.path.expanduser('~/.mozilla/firefox'), os.path.expanduser('~/Library/Application Support/Firefox/Profiles'), os.path.expanduser('~/snap/firefox/common/.mozilla/firefox')]
    dbs = [p for r in roots for p in glob.glob(os.path.join(r, '*', 'cookies.sqlite'))]
    if not dbs: raise RuntimeError('профиль Firefox не найден')
    src, out = max(dbs, key=os.path.getmtime), []
    with tempfile.TemporaryDirectory() as t:
        for e_ in ('', '-wal', '-shm'):
            if os.path.exists(src + e_): shutil.copy(src + e_, os.path.join(t, 'c.sqlite' + e_))
        con = sqlite3.connect(os.path.join(t, 'c.sqlite'))
        for n, v, h, p, e, sec, ho, ss in con.execute('select name,value,host,path,expiry,isSecure,isHttpOnly,sameSite from moz_cookies where host like ?', ('%' + domain,)):
            exp = e / 1000.0 if e > 1e11 else float(e)
            out.append({'name': n, 'value': v, 'domain': h, 'path': p, 'expires': exp if exp > 0 else -1, 'secure': bool(sec), 'httpOnly': bool(ho), 'sameSite': {0: 'None', 1: 'Lax', 2: 'Strict'}.get(ss, 'Lax') if (ss != 0 or sec) else 'Lax'})
        con.close()
    return out
def browser_cookies(domain):  # cookie вашего браузера только для этого сайта (нужны для входа)
    b = (cfg.get('cookie_browser') or '').lower()
    if not b: return []
    if b == 'firefox': return firefox_cookies(domain)
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(b)
    except Exception as e:
        raise RuntimeError(f'{b}: cookie недоступны (браузер шифрует их и блокирует базу, пока открыт; закройте {b} или скачивайте мангу через расширение). {str(e)[:90]}')
    return [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path or '/', 'secure': bool(c.secure), 'expires': float(c.expires) if c.expires else -1} for c in jar if domain in (c.domain or '')]
def manga_browser(job):  # те же шаги, что в manga_site, но сайт открывает расширение в браузере пользователя: его вход, его cookie
    mt = manga_url(job['url'])
    if not mt: raise RuntimeError(NO_MANGA)
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер (Яндекс, Firefox, Edge или Chrome) с установленным расширением')
    site, slug = mt; bad = {}; okn = [0]; N = 0; warn = ''; pool = ThreadPoolExecutor(3)
    try:
        job['title'] = 'открываю тайтл в вашем браузере…'
        d = xtask('manga_list', {'url': f'{site}/manga/{slug}/chapters', 'site': site}, 240, job)
        title = (d.get('title') or slug).strip(); exp = int(d.get('expected') or 0); chs = [c for c in d.get('chapters', []) if c.get('cid')][::-1]
        if not chs: raise RuntimeError('главы не найдены')
        if exp and len(chs) < exp - 1: warn = f' Найдено глав {len(chs)}, а на сайте указано {exp}: повторите загрузку.'
        fast = Fast(d.get('ua') or 'Mozilla/5.0', [], site); folder = root('Manga') / safe(title)[:60]
        manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': d.get('cover') or '', 'listed': [{'cid': c['cid'], 'label': c['label']} for c in chs]}, fast.get)
        sel = chs[(job.get('first') or 1) - 1:(job.get('last') or len(chs))]; N = len(sel); pending, retry, fin, t0 = [], [], [0], time.time(); noop = lambda k, n: None
        def reap(keep):
            while pending and (len(pending) > keep or pending[0][0].done()):
                f, c, d2 = pending.pop(0)
                try: ok = f.result()
                except Exception: ok = False
                if ok: okn[0] += 1; fin[0] += 1; joblog(folder, c['label'] + ': ok')
                else: retry.append((c, d2))
            job['pct'] = min(99, int((fin[0] + len(retry)) * 100 / N))
        for i, c in enumerate(sel, 1):
            if job['cancel']: break
            job['title'] = f"{title} · глава {i}/{N} · {c['label']}" + (f' · качается {len(pending)}' if pending else ''); job['eta'] = int((time.time() - t0) / i * (N - i))
            if chapter_done(folder, c['cid']): okn[0] += 1; fin[0] += 1; continue
            err, pages = '', None
            for _ in range(TRIES):
                try:
                    r = xtask('manga_pages', {'url': c['url'], 'site': site}, 300, job); pages = r.get('pages') or []
                    if r.get('error') or not pages or (r.get('total') and len(pages) < int(r['total'])): raise RuntimeError(r.get('error') or f"страниц {len(pages)} из {r.get('total')}")
                    break
                except Exception as e: err = (str(e).splitlines() or [repr(e)])[0][:160]; pages = None
            if not pages: bad[c['label']] = err; fin[0] += 1; joblog(folder, f"{c['label']}: {err}"); continue
            d2 = {'slug': slug, 'cid': c['cid'], 'title': title, 'label': c['label'], 'expected': len(pages), 'pages': pages}
            pending.append((pool.submit(manga_chapter, job, d2, fast.get, noop, 8), c, d2)); reap(2)
        reap(0)
        for c, d2 in retry:
            if job['cancel']: break
            job['title'] = f"{title} · повторная загрузка · {c['label']}"
            if manga_chapter(job, d2, fast.get, noop): okn[0] += 1; joblog(folder, c['label'] + ': ok (повтор)')
            else: bad[c['label']] = 'не все страницы скачались'; joblog(folder, c['label'] + ': не все страницы скачались')
    finally:
        pool.shutdown()
        try: xtask('manga_done', {}, 20)
        except Exception: pass
    job['final'] = (f'готово: {okn[0]} из {N} глав.' if not bad else f'частично: {okn[0]} из {N} глав. Не удалось: ' + '; '.join(f'{k} ({v})' for k, v in list(bad.items())[:3])) + warn

# ---------- библиотека игр: карточка из страницы темы, версии, обновления ----------
import gamelib, gameupdate, gamelink
def name_key(name):
    import gamesweep
    return gamesweep.parse_name(name)['key'] or re.sub(r'\W+', '', str(name).casefold())
def ginfo(r):
    try: return json.loads(r['info'] or '{}')
    except Exception: return {}
def ginfo_save(rid, info): sql('update items set info=? where id=?', (json.dumps(info, ensure_ascii=False), rid))
def find_game(key, title=''):  # сначала точный ключ, затем похожее название (папка и тема называются по-разному)
    r = sql("select * from items where kind='game' and url=?", ('game:' + key,))
    if r: return r[0]
    import difflib
    best, score = None, 0.0
    for x in sql("select * from items where kind='game'"):
        k = x['url'][5:] if str(x['url']).startswith('game:') else name_key(x['title'])
        s = difflib.SequenceMatcher(None, k, key).ratio()
        if s > score: best, score = x, s
    return best if score >= 0.9 else None
def card_by_memory(ms, links):  # название не совпало ни с одной карточкой: вспоминаем по записанной связи, затем по маркеру в папке → (строка, способ)
    for g, _ in ms:
        i = links.get(os.path.abspath(g['path']))
        r = sql("select * from items where kind='game' and id=?", (i,)) if i else []
        if r: return r[0], 'link'
    for g, _ in ms:
        m = gamelink.read_marker(g['path']) if g.get('type') == 'folder' else None
        if not m: continue
        r = (sql("select * from items where kind='game' and src=?", (m['thread'],)) if m['thread'] else []) or (sql("select * from items where kind='game' and url=?", ('game:' + m['key'],)) if m['key'] else [])
        if r: return r[0], 'marker'
    return None, ''
def game_sources(i):  # сборки карточки по сайтам: у каждой своя версия, размер, язык и ссылки (F95zone первой)
    srcs = dict(i.get('sources') or {}); meta = i.get('meta') or {}
    if meta and (meta.get('site') or 'f95') not in srcs: srcs[meta.get('site') or 'f95'] = dict(meta)   # карточка добавлена до появления источников
    out = []
    for site, m in srcs.items():
        lang = m.get('language', '')
        out.append({'site': site, 'name': m.get('site_name') or {'f95': 'F95zone'}.get(site, site), 'url': m.get('thread', ''), 'version': m.get('version', ''), 'latest': m.get('latest', ''), 'size': m.get('size', ''),
                    'russian': m.get('russian') or engine_games.russian_of(interface=lang), 'language': lang, 'censor': m.get('censor', ''), 'release_type': m.get('release_type', ''), 'seeds': m.get('seeds', 0),
                    'torrent': m.get('torrent', ''), 'magnet': m.get('magnet', ''), 'needs_login': bool(m.get('needs_login')), 'updated': m.get('updated', ''), 'status': m.get('status', ''), 'checked': m.get('checked', 0),
                    'registered': m.get('registered', ''), 'steam_reviews': m.get('steam_reviews', ''), 'alt': m.get('alt', []), 'tags': m.get('genres', []), 'primary': m.get('thread') == meta.get('thread')})
    return sorted(out, key=lambda s: (s['site'] != 'f95', s['name']))
def game_view(r):  # всё, что нужно карточке в библиотеке
    i = ginfo(r); m = i.get('meta', {}); inst = i.get('inst', {}); dl = bool(r['path'] and Path(r['path']).exists()); srcs = game_sources(i)
    tags = list(dict.fromkeys(t for s in sorted(srcs, key=lambda s: not s['primary']) for t in s['tags']))   # теги всех сборок без повторов, главная первой
    ru = next((v for v in ('yes', 'voice', 'sub') if any(s['russian'] == v for s in srcs)), 'no' if srcs and all(s['russian'] == 'no' for s in srcs) else '?')
    return {'downloaded': dl, 'version': inst.get('version', '') if dl else '', 'latest': m.get('version', ''), 'update': bool(i.get('update') and dl), 'genres': tags or m.get('genres', []), 'sources': srcs, 'russian': ru, 'developer': m.get('developer', ''),
            'engine': m.get('engine', ''), 'os': m.get('os', ''), 'status': m.get('status', ''), 'release': m.get('release', ''), 'desc': m.get('desc', ''), 'links': m.get('links', []), 'support': m.get('support', []), 'thread': m.get('thread') or '',
            'language': m.get('language', ''), 'auto': i.get('auto', True), 'note': i.get('note', ''), 'checked': i.get('checked', 0), 'added': i.get('added', 0), 'versions': inst.get('versions', 1 if dl else 0), 'old': inst.get('old', 0), 'path': r['path'] if dl else ''}
def fetch_cover(url, referer, key):
    guard(url)
    with opener().open(urllib.request.Request(url, headers={**UA, 'Referer': referer}), timeout=30) as r: data = r.read(8_000_000)
    ext = sniff(data)
    if not ext: return ''
    d = root('Games') / 'covers'; d.mkdir(parents=True, exist_ok=True); p = d / (safe(key)[:80] + '.' + ext); p.write_bytes(data); return str(p)
def game_engine(url):  # какой разборщик у страницы игры: f95 (по умолчанию), pornolab или byrutor — по профилю сайта в sites.json
    p = siteprofiles.match(SITES, siteprofiles.host_of(url), urlparse(url).path, ('game',)); return siteprofiles.engine_of(p) if p else 'f95'
def game_key(url): e = game_engine(url); return engine_games.source_key(e, url) if e in ('pornolab', 'byrutor') else gamelib.thread_key(url)
def read_game(url, job=None):  # страница игры в вашем браузере -> сведения об игре и сборке
    return {'pornolab': engine_games.parse_pornolab, 'byrutor': engine_games.parse_byrutor}.get(game_engine(url), gamelib.parse_thread)(fetch_html(url, job), url)
def game_threads(i):  # все страницы-источники карточки: f95, pornolab, byrutor
    return list(dict.fromkeys([s['thread'] for s in (i.get('sources') or {}).values() if s.get('thread')] + ([i['meta']['thread']] if i.get('meta', {}).get('thread') else [])))
def apply_meta(meta, thread):  # создаёт или обновляет карточку игры; установленные файлы не трогаем
    name = meta['name'] or thread; key = name_key(name); row = find_game(key, name); info = ginfo(row) if row else {}
    site = meta.get('site') or 'f95'; meta = dict(meta, thread=thread, site=site, site_name=meta.get('site_name') or {'f95': 'F95zone'}.get(site, site))
    info.setdefault('sources', {})[site] = dict(meta, checked=time.time())   # у каждого сайта своя версия, размер и язык: сборки хранятся отдельно
    prev = info.get('meta') or {}
    if not prev or (prev.get('site') or 'f95') == site or site == 'f95': info['meta'] = meta   # главной остаётся тема F95zone, пока она есть; иначе первый добавленный источник
    info['checked'] = time.time(); info.setdefault('added', time.time()); info.setdefault('auto', True)
    inst = info.get('inst', {}).get('version', ''); info['update'] = bool(inst and any(gamelib.newer(s.get('version', ''), inst) for s in info['sources'].values()))
    cover = ''; has_thumb = bool(row and row['thumb'] and Path(row['thumb']).exists()); primary = info['meta'].get('thread') == thread
    if meta.get('cover') and (primary or not has_thumb) and not (has_thumb and info.get('cover_src') == meta['cover']):
        try: cover = fetch_cover(meta['cover'], thread, key); info['cover_src'] = meta['cover']
        except Exception: cover = ''
    if row:
        sql("update items set title=?, author=?, src=?, info=?, thumb=case when ?='' then thumb else ? end where id=?", (name if primary else row['title'], (meta.get('developer') or row['author']) if primary else row['author'], info['meta']['thread'], json.dumps(info, ensure_ascii=False), cover, cover, row['id']))
        return row['id']
    sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)", (name, meta.get('developer') or 'Игры', 'Игры', 'game', '', '', 'game:' + key, 0, cover, thread, json.dumps(info, ensure_ascii=False)))
    return sql("select id from items where url=?", ('game:' + key,))[0]['id']
def fetch_html(url, job=None):
    d = xtask('fetch_html', {'url': url, 'site': '{0.scheme}://{0.netloc}'.format(urlparse(url))}, 180, job); return d.get('html') or ''
def game_card(job):  # вкладка (или список ссылок) в браузере -> карточки игр, по одной с паузой
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер с установленным расширением')
    urls = job.get('urls') or [job['url']]; many = len(urls) > 1; delay = float(os.environ.get('MEDIAHUB_GAME_DELAY', cfg.get('games_delay') or 8)) if many else 0
    done, bad, had = [], [], 0
    for k, url in enumerate(urls):
        if job['cancel']: break
        if many and sql("select 1 from items where kind='game' and src=?", (game_key(url),)):   # в списке из многих ссылок уже добавленные не перечитываем
            had += 1; job['pct'] = int((k + 1) * 100 / len(urls)); continue
        job['title'] = (f'читаю страницу игры {k + 1}/{len(urls)}…' if many else 'читаю страницу игры в вашем браузере…'); job['pct'] = int(k * 100 / len(urls))
        try:
            meta = read_game(url, job)
            if meta.get('blocked'): raise RuntimeError('сайт показал проверку Cloudflare вместо страницы: откройте сайт в этом браузере, пройдите проверку и повторите')
            if not meta['name']: raise RuntimeError('на странице не нашлось названия игры (нужен вход на сайт?)')
            apply_meta(meta, game_key(url)); done.append(meta)
        except Exception as e:
            if not many: raise
            bad.append(f'{url}: {str(e)[:80]}')
        if k < len(urls) - 1 and delay and not job['cancel']: time.sleep(delay)
    if not many: m = done[0]; job['title'] = 'Карточка: ' + m['name']; job['final'] = f"готово: «{m['name']}», версия {m['version'] or 'не указана'}"; return
    job['title'] = f'Карточки игр: {len(done)} из {len(urls)}'
    job['final'] = f'готово: добавлено {len(done)} из {len(urls)}' + (f', уже были в библиотеке: {had}' if had else '') + (f'. Не удалось: {len(bad)} ({bad[0]})' if bad else '')
def game_replace(job):  # старые версии -> новая: сохранения и перевод переезжают, старые уходят в Корзину (после подтверждения в окне)
    root_ = cfg.get('games_root') or ''; st = games_store()
    with st.lock: keepers = {m['path']: gr for gr in st.groups for m in gr['members'] if m['status'] == 'оставить'}
    ids_ = job['ids']; ok = sv = tl = 0; bad = []
    for k, rid in enumerate(ids_):
        if job['cancel']: break
        r_ = sql("select title,path from items where id=? and kind='game'", (rid,)); nm = r_[0]['title'] if r_ else str(rid)
        job['title'] = f'Заменяю версии {k + 1}/{len(ids_)}: {nm}'; job['pct'] = int(k * 100 / len(ids_))
        pl = gameupdate.plan(keepers[r_[0]['path']]) if r_ and r_[0]['path'] in keepers else None
        if not pl or not pl['can']: bad.append(f"{nm}: {(pl or {}).get('why') or 'у игры нет старых версий'}"); continue
        res = gameupdate.replace(pl['keeper']['path'], [o['path'] for o in pl['olds']], root_, job.get('delete_old', True))
        if res['ok']: ok += 1; sv += res['saves']; tl += res['tl']
        if res['msg']: bad.append(f"{nm}: {res['msg']}")
    if ok: games_scan(root_)
    job['title'] = f'Замена версий: {ok} из {len(ids_)}'
    if not ok and bad: raise RuntimeError(bad[0])
    job['final'] = ('частично' if bad else 'готово') + f': заменено {ok} из {len(ids_)}, сохранений перенесено {sv}, файлов перевода {tl}' + (f'. Замечания: {len(bad)} ({bad[0]})' if bad else '')
def game_check(job):  # проверка новых версий: по одной странице в вашем браузере, неторопливо
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер с установленным расширением')
    ids = job.get('ids') or [r['id'] for r in sql("select * from items where kind='game'") if game_threads(ginfo(r))]
    work = [(rid, th) for rid in ids for th in game_threads(ginfo((sql('select * from items where id=?', (rid,)) or [{'info': '{}'}])[0]))]   # по странице на каждый источник карточки
    delay = float(os.environ.get('MEDIAHUB_GAME_DELAY', cfg.get('games_delay') or 8)); n = upd = 0; bad = []
    for k, (rid, th) in enumerate(work):
        if job['cancel']: break
        rows = sql('select * from items where id=?', (rid,))
        if not rows: continue
        r = rows[0]; i = ginfo(r)
        job['title'] = f"Проверка игр {k + 1}/{len(work)}: {r['title']}"; job['pct'] = int(k * 100 / max(1, len(work)))
        try:
            meta = read_game(th, job)
            if meta.get('blocked'): raise RuntimeError('проверка Cloudflare: пройдите её в браузере')
            if not meta['name']: raise RuntimeError('страница не открылась')
            old = next((s.get('version', '') for s in (i.get('sources') or {}).values() if s.get('thread') == th), i.get('meta', {}).get('version', '')); apply_meta(meta, th); n += 1
            if meta.get('version') and meta['version'] != old:
                upd += 1; ev = feedlib.game_event(rid, r['title'], meta.get('site') or 'f95', meta.get('site_name') or {'f95': 'F95zone'}.get(meta.get('site') or 'f95', ''), old, meta['version'], th)
                if ev: feed_add(ev)   # в ленту: «версия изменилась»
        except Exception as e: bad.append(f"{r['title']}: {str(e)[:60]}")
        if k < len(work) - 1 and delay: time.sleep(delay)
    job['final'] = f'готово: проверено {n}, изменилась версия у {upd}' + (f'. Не удалось: {len(bad)} ({bad[0]})' if bad else '')
# ---------- лента обновлений: проверить источник → сравнить → событие ----------
def cfg_save(): CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), 'utf-8')
def feed_add(ev):  # True, если такого события ещё не было
    if sql('select 1 from feed where key=?', (ev['key'],)): return False
    sql('insert into feed(kind,key,item_id,title,detail,url,action,payload,at) values(?,?,?,?,?,?,?,?,?)', (ev['kind'], ev['key'], ev.get('item_id'), ev['title'], ev['detail'], ev.get('url') or '', ev.get('action') or 'open', json.dumps(ev.get('payload') or {}, ensure_ascii=False), time.time()))
    if ev['kind'] == 'manga' and ev.get('item_id'): sql("delete from feed where kind='manga' and item_id=? and seen=0 and key<>?", (ev['item_id'], ev['key']))   # новое событие заменяет прежнее непрочитанное по тому же тайтлу
    return True
def list_videos(url, limit=30):  # название и последние записи канала или плейлиста (без скачивания): (title, [{id, title, url}])
    import yt_dlp
    o = base(); o.update(extract_flat='in_playlist', skip_download=True, ignoreerrors=True, playlistend=limit)
    with yt_dlp.YoutubeDL(o) as y: t = y.extract_info(url, download=False) or {}
    return t.get('title') or '', [{'id': e.get('id'), 'title': e.get('title') or '', 'url': e.get('url') or e.get('webpage_url') or ''} for e in (t.get('entries') or []) if e]
def manga_source(man, r):  # адрес тайтла: из манифеста, а у тайтлов, скачанных раньше, по сайту и slug
    if man.get('source'): return man['source']
    slug = man.get('slug') or ''; p = next((s for s in SITES if s['kind'] == 'manga' and s.get('name') == r['author'] and siteprofiles.engine_of(s) != 'nudemoon'), None)
    return f"https://{p['hosts'][0]}/manga/{slug}" if p and slug else ''
def feed_check(job):  # проверка по видам; игры проверяются своим заданием (по странице в вашем браузере, неторопливо)
    kinds = [k for k in (job.get('kinds') or feedlib.KINDS) if k in feedlib.KINDS]; found = dict.fromkeys(feedlib.KINDS, 0); notes = []; delay = float(os.environ.get('MEDIAHUB_FEED_DELAY', cfg.get('feed_delay') or 3))
    if 'manga' in kinds:
        rows = sql("select * from items where kind='manga'"); get_html = html_source(job); skipped = 0
        for k, r in enumerate(rows):
            if job['cancel']: break
            job['title'] = f"Лента: манга {k + 1}/{len(rows)}: {r['title']}"; job['pct'] = int(k * 60 / max(1, len(rows)))
            try: man = json.loads((Path(r['root']) / 'manifest.json').read_text('utf-8'))
            except Exception: continue
            src = manga_source(man, r); prof = siteprofiles.manga_profile(SITES, src) if src else None; mt = siteprofiles.manga_title(SITES, src) if prof else None
            if not mt or siteprofiles.engine_of(prof) != 'mangabuff': skipped += 1; continue   # у остальных сайтов список глав так не прочитать
            try:
                t = engine_mangabuff.load_title(get_html, *mt); known = {c['cid'] for c in man.get('listed', [])} | set(man.get('chapters', {}))
                ev = feedlib.manga_event(r['id'], r['title'], man.get('slug') or mt[1], known, t['chapters'], src)
                if ev and feed_add(ev): found['manga'] += 1
            except Exception as e: notes.append(f"{r['title']}: {str(e).splitlines()[0][:70] if str(e) else 'ошибка'}")
            if delay and k < len(rows) - 1: time.sleep(delay)
        if skipped: notes.append(f'манга: у {skipped} тайтлов проверка глав пока недоступна (сайт не поддержан)')
    if 'video' in kinds:
        ws = sql('select * from watch')
        for k, w in enumerate(ws):
            if job['cancel']: break
            job['title'] = f"Лента: видео {k + 1}/{len(ws)}: {w['title'] or w['url']}"; job['pct'] = 60 + int(k * 30 / max(1, len(ws)))
            try:
                guard(w['url']); title, ents = list_videos(w['url']); ev, seen, ok = feedlib.video_events(w['id'], w['title'] or title, ents, json.loads(w['seen'] or '[]'), bool(w['baselined']))
                sql("update watch set seen=?, baselined=1, checked=?, error='', title=case when title='' then ? else title end where id=?", (json.dumps(seen), time.time(), title, w['id']))
                found['video'] += sum(1 for e in ev if feed_add(e))
            except Exception as e:
                sql('update watch set error=?, checked=? where id=?', (str(e).splitlines()[0][:120] if str(e) else 'ошибка', time.time(), w['id'])); notes.append(f"{w['title'] or w['url']}: не удалось проверить")
    if 'game' in kinds:
        if not ext_online(): notes.append('игры: расширение MediaHub не на связи, проверка игр пропущена')
        elif any(j['kind'] == 'gamecheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()): notes.append('игры: проверка уже идёт')
        else: new_job('games:feed', 'gamecheck', title='Проверка игр (лента)'); notes.append('игры проверяются отдельным заданием, результат появится в ленте')
    total = sum(found.values()); cfg['feed_checked'] = time.time()
    cfg['feed_last'] = (f'новых событий: {total}' if total else 'новых событий нет') + (f" (манга {found['manga']}, видео {found['video']})" if total else ''); cfg_save()
    job['final'] = cfg['feed_last'] + ('. ' + '; '.join(notes[:3]) if notes else '')
def feed_auto_loop():  # по расписанию (feed_hours; 0 = выключено)
    while True:
        time.sleep(60)
        try:
            if feedlib.due(cfg.get('feed_checked', 0), float(cfg.get('feed_hours') or 0), time.time()) and not any(j['kind'] == 'feedcheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()):
                new_job('feed:auto', 'feedcheck', title='Лента: проверка по расписанию')
        except Exception: pass
def feed_view(r): return dict(id=r['id'], kind=r['kind'], title=r['title'], detail=r['detail'], url=r['url'], action=r['action'], at=r['at'], seen=bool(r['seen']), payload=json.loads(r['payload'] or '{}'))
def feed_list(kind='', unseen=False):
    q, a = 'select * from feed where 1=1', []
    if kind in feedlib.KINDS: q += ' and kind=?'; a.append(kind)
    if unseen: q += ' and seen=0'
    unseen_n = {k: n for k, n in sql('select kind, count(*) from feed where seen=0 group by kind')}; ws = sql('select * from watch order by id')
    gm = sql("select info from items where kind='game'"); mg = sql("select * from items where kind='manga'")
    sup = sum(1 for r in mg if (lambda s: bool(s) and siteprofiles.engine_of(siteprofiles.manga_profile(SITES, s)) == 'mangabuff')(manga_source(_manifest(r), r)))
    return {'events': [feed_view(r) for r in sql(q + ' order by seen, at desc limit 300', a)], 'unseen': {k: unseen_n.get(k, 0) for k in feedlib.KINDS}, 'total_unseen': sum(unseen_n.values()),
            'watches': [{'id': w['id'], 'url': w['url'], 'title': w['title'], 'checked': w['checked'], 'error': w['error'], 'baselined': bool(w['baselined'])} for w in ws],
            'tracked': {'game': sum(1 for g in gm if game_threads(json.loads(g['info'] or '{}'))), 'manga': len(mg), 'manga_supported': sup, 'video': len(ws)},
            'status': {'checked': cfg.get('feed_checked', 0), 'last': cfg.get('feed_last', ''), 'hours': float(cfg.get('feed_hours') or 0), 'running': any(j['kind'] == 'feedcheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()), 'ext': ext_online()}}
def _manifest(r):
    try: return json.loads((Path(r['root']) / 'manifest.json').read_text('utf-8'))
    except Exception: return {}
def feed_act(fid):  # главное действие события: скачать новые главы или видео; для игр открывается страница (это делает интерфейс)
    r = (sql('select * from feed where id=?', (fid,)) or [None])[0]
    if not r: return {'error': 'Событие не найдено'}, 404
    if r['action'] == 'download' and r['url']:
        kind = 'mangaurl' if r['kind'] == 'manga' else JOBK.get(classify(r['url'])['kind'], 'video')
        jid = new_job(r['url'], kind, title=r['title']); sql('update feed set seen=1 where id=?', (fid,)); return {'job': jid}, 200
    sql('update feed set seen=1 where id=?', (fid,)); return {'open': r['url']}, 200
def game_auto_loop():  # по расписанию (0 часов = выключено): проверяем игры с включённым «следить»
    while True:
        time.sleep(60)
        try:
            hrs = float(cfg.get('games_check_hours') or 0)
            if hrs > 0 and ext_online() and not any(j['kind'] == 'gamecheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()):
                due = [r['id'] for r in sql("select * from items where kind='game'") if ginfo(r).get('meta', {}).get('thread') and ginfo(r).get('auto', True) and time.time() - ginfo(r).get('checked', 0) > hrs * 3600]
                if due: new_job('games:auto', 'gamecheck', ids=due[:20], title='Проверка игр по расписанию')
        except Exception: pass

# ---------- плеер: позиция воспроизведения ----------
PLAY_KINDS = ('video', 'audio')
def finished(pos, dur): return dur > 0 and pos >= dur - 10  # завершённое воспроизводится с нуля и не попадает в «Продолжить»
def _num(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
def save_pos(i, pos, dur):  # позиция меньше 5 секунд не сохраняется
    if not (_num(pos) and _num(dur)) or pos < 0 or dur < 0: raise ValueError('bad numbers')
    if pos < 5: return False
    sql('insert or replace into playpos(item_id,pos,dur,updated) values(?,?,?,?)', (i, float(pos), float(dur), time.time())); return True
# ---------- субтитры ----------
SUB_EXT = ('.srt', '.vtt'); SUB_LANG = re.compile(r'^[A-Za-z0-9_-]{1,12}$'); SUB_MAX = 5 * 1024 * 1024; SUB_NAMES = {'': 'Субтитры', 'ru': 'Русский', 'en': 'English'}
def sub_files(path):  # [(язык, файл)] рядом с материалом: <имя>.<язык>.srt|vtt и <имя>.srt|vtt; порядок один и тот же для списка и для отдачи
    p = Path(path); d = p.parent; out = []
    try: dr = d.resolve(); names = list(d.iterdir())
    except OSError: return []
    for f in names:
        if f.suffix.lower() not in SUB_EXT: continue
        st = f.stem
        if st == p.stem: lang = ''
        elif st.startswith(p.stem + '.') and SUB_LANG.match(st[len(p.stem) + 1:]): lang = st[len(p.stem) + 1:]
        else: continue
        try:
            if not f.is_file() or f.resolve().parent != dr: continue  # ссылка наружу из папки не отдаётся
        except OSError: continue
        out.append((lang, f))
    return sorted(out, key=lambda t: (t[0], t[1].name))
def sub_label(lang): return SUB_NAMES.get(lang.lower(), lang)
def decode_sub(data):
    try: return data.decode('utf-8-sig')
    except UnicodeDecodeError: return data.decode('cp1251', 'replace')
def srt_to_vtt(text):  # запятая в миллисекундах меняется только в строках таймкодов, текст реплик не трогается
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    if text.lstrip().startswith('WEBVTT'): return text
    text = re.sub(r'^(\s*\d{1,2}:\d{2}:\d{2}),(\d{3}\s+-->\s+\d{1,2}:\d{2}:\d{2}),(\d{3})', r'\1.\2.\3', text, flags=re.M)
    return 'WEBVTT\n\n' + text
def clock(sec):
    sec = int(max(sec, 0)); h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
def rest_label(left):
    if left < 60: return 'осталось меньше минуты'
    mins = math.ceil(left / 60); h, m = divmod(mins, 60)
    if h == 0: return f'осталось {m} мин'
    return f'осталось {h} ч' + (f' {m} мин' if m else '')
def continue_items(limit=6):  # видео/аудио с позицией и манга с прогрессом, свежие первыми
    out = []
    for r in sql('select i.id,i.title,i.kind,i.thumb,p.pos,p.dur,p.updated u from playpos p join items i on i.id=p.item_id where i.kind in (?,?)', PLAY_KINDS):
        if r['pos'] < 5 or finished(r['pos'], r['dur']): continue
        dur = r['dur']
        out.append({'u': r['u'] or 0, 'id': r['id'], 'kind': r['kind'], 'title': r['title'], 'cover': f"/t/{r['id']}" if r['thumb'] else '', 'open': f"/p/{r['id']}",
                    'pos': r['pos'], 'dur': dur, 'pct': round(100 * r['pos'] / dur) if dur > 0 else 0, 'label': rest_label(dur - r['pos']) if dur > 0 else 'остановлено на ' + clock(r['pos'])})
    for r in sql("select i.id,i.title,i.thumb,g.cid,g.page,g.updated u from items i join progress g on g.slug=substr(i.url,7) where i.kind='manga'"):
        try: info = manga_info(r['id']); have = [c for c in info['chapters'] if c['files']]
        except Exception: continue  # нет или повреждён manifest.json: тайтл в «Продолжить» не показываем
        cur = next((c for c in info['chapters'] if c['id'] == r['cid']), None)
        if not cur: continue
        pos = next((k + 1 for k, c in enumerate(have) if c['id'] == r['cid']), 0)
        lab = cur['label'] or ''
        out.append({'u': r['u'] or 0, 'id': r['id'], 'kind': 'manga', 'title': r['title'], 'cover': f"/t/{r['id']}" if r['thumb'] else '', 'open': f"/m/{r['id']}",
                    'pos': r['page'], 'dur': 0, 'pct': round(100 * pos / len(have)) if have else 0, 'label': f"{lab[:1].lower() + lab[1:]}, стр. {r['page'] + 1}"})
    out.sort(key=lambda x: -x['u'])
    for x in out: del x['u']
    return out[:limit]
def play_state(i):
    r = sql('select * from items where id=?', (i,))
    if not r or r[0]['kind'] not in PLAY_KINDS: return None
    r = r[0]; pp = sql('select pos,dur from playpos where item_id=?', (i,)); pos, dur = (pp[0]['pos'], pp[0]['dur']) if pp else (0, 0)
    return {'id': r['id'], 'title': r['title'], 'kind': r['kind'], 'src': f"/f/{r['id']}", 'cover': cover_of(r), 'pos': pos, 'dur': dur, 'finished': finished(pos, dur),
            'subs': [{'n': n, 'lang': lg, 'label': sub_label(lg), 'url': f"/sub/{r['id']}/{n}.vtt"} for n, (lg, _) in enumerate(sub_files(r['path']))]}

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def blob(self, data, ctype):
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def js(self, o, code=200):
        if getattr(self, 'guest', False): o = lan.scrub(o, drop_games=True)   # гостю не отдаём пути на диске и игры
        b = json.dumps(o, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', len(b))
        if getattr(self, '_aco', ''): self.send_header('Access-Control-Allow-Origin', self._aco)
        self.end_headers(); self.wfile.write(b)
    def file(self, p, ctype=None):
        p = Path(p)
        if not p.is_file(): return self.send_error(404)
        size = p.stat().st_size; a, b = 0, size - 1; m = re.match(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
        if m:
            if m.group(1): a = int(m.group(1))
            if m.group(2): b = min(int(m.group(2)), size - 1)
        self.send_response(206 if m else 200)
        self.send_header('Content-Type', ctype or mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', b - a + 1)
        if m: self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
        self.end_headers()
        with open(p, 'rb') as f:
            f.seek(a); left = b - a + 1
            while left > 0:
                c = f.read(min(1 << 20, left))
                if not c: break
                try: self.wfile.write(c)
                except OSError: return
                left -= len(c)
    def do_OPTIONS(self):
        if not self.host_ok(): return self.send_error(403)
        o = self.headers.get('Origin') or ''; allow = o if o.startswith(('chrome-extension://', 'moz-extension://')) else (o if o in ('https://senkuro.me', 'https://www.senkuro.me') else '')
        self.send_response(204)
        if allow:
            for k, v in {'Access-Control-Allow-Origin': allow, 'Access-Control-Allow-Methods': 'GET, POST', 'Access-Control-Allow-Headers': 'Content-Type, X-MH-Token', 'Access-Control-Allow-Private-Network': 'true', 'Access-Control-Max-Age': '600'}.items(): self.send_header(k, v)
        self.end_headers()
    def ext_origin(self):
        o = self.headers.get('Origin') or ''; return o if o.startswith(('chrome-extension://', 'moz-extension://')) else ''
    def ext_ok(self, o):  # доступ по секретному токену: Chrome не присылает Origin в GET-запросах расширения, поэтому к Origin не привязываемся
        t = self.headers.get('X-MH-Token') or ''; ok = bool(t) and any(hmac.compare_digest(v, t) for v in EXT.values())
        if ok: EXT_SEEN[0] = time.time()
        return ok
    def ext_get(self, p, qs):  # расширение опрашивает приложение: какие вкладки пора закрыть
        o = self.ext_origin(); self._aco = o or '*'
        if not self.ext_ok(o): return self.js({'error': 'auth'}, 401)
        if p == '/ext/commands':
            end = time.time() + min(25.0, float(qs.get('wait') or 0))
            while True:
                settle(); rows = sql("select * from inbox where cmd!=''"); tasks = take_tasks(); EXT_SEEN[0] = time.time()
                if rows or tasks or time.time() >= end: break
                time.sleep(0.5)
            return self.js({'commands': [{'id': r['id'], 'cmd': r['cmd'], 'tab_id': r['tab_id'], 'url': r['url'], 'title': r['title']} for r in rows] + [{'cmd': 'task', 'task': t['id'], 'type': t['type'], 'payload': t['payload']} for t in tasks]})
        if p == '/ext/ping': return self.js({'ok': 1})
        self.send_error(404)
    def ext_post(self):
        o = self.ext_origin(); self._aco = o or '*'; d = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 2_000_000)) or b'{}')
        if self.path == '/ext/hello':  # знакомство: токен выдаётся только после согласия человека в приложении
            if not o: return self.js({'error': 'origin'}, 403)
            if o in EXT: return self.js({'status': 'ok', 'token': EXT[o]})
            PAIR[o] = {'name': str(d.get('name') or 'Браузер')[:40], 't': time.time()}; return self.js({'status': 'pending'})
        if not self.ext_ok(o): return self.js({'error': 'auth'}, 401)
        if self.path == '/ext/result':  # расширение вернуло результат задания (список глав, адреса страниц)
            with XTL: t = XT.get(d.get('id'))
            if t: t['res'] = {'ok': bool(d.get('ok')), 'data': d.get('data'), 'error': d.get('error')}; t['ev'].set()
            return self.js({'ok': 1})
        if self.path == '/ext/tabs':
            batch, n = inbox_add(d.get('tabs') or [], bool(d.get('close')), str(d.get('browser') or ''), bool(d.get('site')))
            if d.get('auto'):  # «Добавить всё»: без промежуточного списка, действия берутся по типу материала
                rows = [{'id': r['id'], 'action': r['action'], 'kind': r['kind']} for r in sql("select * from inbox where batch=? and status='pending'", (batch,))]
                res = inbox_confirm({'batch': batch, 'close': bool(d.get('close')), 'rows': rows}); return self.js({'batch': batch, 'count': n, **res})
            return self.js({'batch': batch, 'count': n})
        if self.path == '/ext/ack':
            r = sql('select * from inbox where id=?', (d.get('id'),)); res = d.get('result')
            if r: sql('update inbox set cmd=?, status=?, reason=? where id=?', ('', 'closed' if res in ('closed', 'missing') else 'kept', {'cancelled': 'вы отменили закрытие', 'moved': 'вкладка уже открыта на другой странице', 'failed': 'браузер не дал закрыть вкладку'}.get(res, ''), r[0]['id']))
            return self.js({'ok': 1})
        self.send_error(404)
    def ingest(self):  # приём глав/обложки от закладки (только с senkuro.me)
        raw = self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 4_000_000)).decode('utf-8', 'ignore'); test = os.environ.get('MEDIAHUB_TEST_ALLOW_LOCAL') == '1'
        if self.headers.get('Origin') not in ('https://senkuro.me', 'https://www.senkuro.me') and not test: return self.send_error(403)
        try:
            if raw.startswith('data='): raw = parse_qs(raw)['data'][0]
            d = json.loads(raw); slug = str(d['slug']); cid = str(d.get('cid', ''))
            ok = lambda u: isinstance(u, str) and ((urlparse(u).hostname in MH and u.startswith('https://')) or test)
            assert re.fullmatch(r'[a-z0-9-]{1,300}', slug) and (not cid or re.fullmatch(r'\d{1,30}', cid))
            m = {'slug': slug, 'cid': cid, 'title': str(d['title'])[:200] or slug[:60], 'label': str(d.get('label', ''))[:80], 'expected': min(int(d.get('expected') or 0), 600),
                 'pages': [u for u in d.get('pages', [])[:600] if ok(u)], 'cover': d['cover'] if ok(d.get('cover')) else '',
                 'listed': [{'cid': str(c['cid']), 'label': str(c.get('label', ''))[:80]} for c in d.get('listed', [])[:2000] if isinstance(c, dict) and re.fullmatch(r'\d{1,30}', str(c.get('cid', '')))]}
            assert (m['pages'] and cid) or m['cover'] or m['listed']
        except Exception: return self.send_error(400)
        enqueue({'id': next(ids), 'url': 'manga:' + slug, 'kind': 'manga', 'm': m, 'topic': '', 'daily': False, 'start_at': 0, 'status': 'в очереди', 'pct': 0,
                 'title': (m['title'] + ' ' + m['label']).strip(), 'speed': 0, 'eta': 0, 'cancel': False})
        self.send_response(200); self.send_header('Access-Control-Allow-Origin', 'https://senkuro.me'); self.send_header('Content-Length', 2); self.end_headers(); self.wfile.write(b'ok')
    def host_ok(self): return (self.headers.get('Host') or '').split(':')[0] in ('127.0.0.1', 'localhost')
    def remote(self): return self.client_address[0] not in ('127.0.0.1', '::1') or bool(os.environ.get('MEDIAHUB_TEST_REMOTE'))   # переменная только для тестов: считать и свой компьютер «чужим»
    def page(self, code, body, headers=()):
        self.send_response(code); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', len(body)); self.send_header('Cache-Control', 'no-store')
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def login(self, method):  # вход по PIN с другого устройства
        ip = self.client_address[0]; host = self.headers.get('Host') or ''
        if method == 'GET': return self.page(200, lan.login_page())
        if not lan.same_origin(self.headers.get('Origin'), host): return self.send_error(403)
        wait = THR.wait(ip)
        if wait: return self.page(429, lan.login_page(f'Слишком много попыток. Подождите {max(1, wait // 60 + 1)} мин.'))
        try: n = min(int(self.headers.get('Content-Length') or 0), 1024)
        except ValueError: n = 0
        pin = (parse_qs(self.rfile.read(n).decode('utf-8', 'replace')).get('pin') or [''])[0]
        if lan.check_pin(pin, cfg.get('lan_pin_salt', ''), cfg.get('lan_pin_hash', '')):
            THR.ok(ip); return self.page(303, b'', [('Location', '/'), ('Set-Cookie', f'{lan.COOKIE}={SESS.new()}; HttpOnly; SameSite=Strict; Path=/; Max-Age={lan.SESSION_TTL}')])
        THR.fail(ip); return self.page(401, lan.login_page('Неверный PIN'))
    def gate(self, method):  # запрос не с этого компьютера: только при включённом режиме, с PIN и в рамках прав гостя; True — можно обрабатывать
        path = unquote(urlparse(self.path).path); host = self.headers.get('Host') or ''
        deny = lambda msg, code=403: (self.js({'error': msg}, code), False)[1]
        if not (LAN_BOUND or os.environ.get('MEDIAHUB_TEST_REMOTE')) or not lan.host_allowed(host) or path.startswith(('/ext/', '/api/ext')) or path == '/ingest': return self.send_error(403) or False
        if path == '/login': self.login(method); return False
        ck = SimpleCookie(self.headers.get('Cookie') or '').get(lan.COOKIE)
        if not SESS.ok(ck.value if ck else ''):
            if method == 'GET' and not path.startswith(('/api/', '/mi/', '/sub/')): self.page(303, b'', [('Location', '/login')]); return False
            return deny('Нужен вход: введите PIN', 401)
        if not lan.guest_allowed(method, path): return deny('Это действие доступно только на компьютере, где запущено приложение')
        iid = lan.item_id_of(path)
        if iid and (sql('select kind from items where id=?', (iid,)) or [{'kind': ''}])[0]['kind'] == 'game': return deny('Игры доступны только на компьютере с приложением')
        if method == 'POST' and (self.headers.get('X-MH') != '1' or not lan.same_origin(self.headers.get('Origin'), host)): return deny('запрос отклонён')
        self.guest = True; return True
    def do_GET(self):
        if self.remote():
            if not self.gate('GET'): return
        elif not self.host_ok(): return self.send_error(403)
        try: self.get()
        except Exception as e: self.js({'error': str(e)}, 500)
    def get(self):
        u = urlparse(self.path); p = unquote(u.path); qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if p == '/': return self.file(BASE / 'index.html')
        ms = re.match(r'/(js|css)/([\w./-]+)\.(js|css)$', p)
        if ms and ms.group(1) == ms.group(3):
            d = (BASE / ms.group(1)).resolve(); f = (d / (ms.group(2) + '.' + ms.group(3))).resolve()
            if d in f.parents: return self.file(f, 'text/javascript; charset=utf-8' if ms.group(3) == 'js' else 'text/css; charset=utf-8')
            return self.send_error(404)
        if p == '/api/jobs':
            now = time.time(); keys = ('id', 'url', 'kind', 'status', 'pct', 'title', 'eta', 'daily', 'start_at')
            return self.js([dict({k: j.get(k) for k in keys}, speed=(j.get('speed') or 0) if now - j.get('_ts', now) < 8 else 0) for j in jobs.values()])
        if p.startswith('/ext/'): return self.ext_get(p, qs)
        if p == '/api/inbox': return self.js(inbox_state())
        if p == '/api/ext':
            for o in [o for o, v in PAIR.items() if time.time() - v['t'] > 150]: PAIR.pop(o, None)
            return self.js({'pending': [{'origin': o, 'name': v['name']} for o, v in PAIR.items()], 'paired': list(EXT), 'ext_dir': str(BASE / 'extension'), 'ext_ff': str(BASE / 'extension-firefox' / 'manifest.json'), 'inbox_pending': sql("select count(*) n from inbox where status='pending'")[0]['n']})
        if p == '/api/settings': return self.js(cfg_public())
        if p == '/api/feed': return self.js(feed_list(qs.get('kind', ''), qs.get('unseen') == '1'))
        if p == '/api/feed/count': return self.js({'unseen': sql('select count(*) from feed where seen=0')[0][0]})
        if p == '/api/lan': return self.js({'enabled': bool(cfg.get('lan')), 'bound': LAN_BOUND, 'pin_set': bool(cfg.get('lan_pin_hash')), 'sessions': SESS.count(), 'restart': bool(cfg.get('lan') and cfg.get('lan_pin_hash')) != LAN_BOUND,
                                           'addresses': [f'http://{a}:{self.server.server_address[1]}' for a in lan.local_addresses()]})
        if p == '/api/sites': return self.js({'manga': list(MANGA_HOSTS)})
        if p == '/api/versions/state': return self.js(games_store().snapshot())   # результат последнего сканирования папки игр: группы версий и сводка
        if p == '/api/game/plans':   # у каких игр есть старые версии и что будет сделано при замене (ничего не меняет)
            st = games_store()
            with st.lock: groups = list(st.groups)
            items = []
            for gr in groups:
                pl = gameupdate.plan(gr)
                if not pl['olds']: continue
                r_ = sql("select id from items where kind='game' and path=?", (pl['keeper']['path'],)) if pl['keeper'] else []
                if r_: items.append(dict(pl, id=r_[0]['id']))
            return self.js({'items': items, 'running': st.running, 'scanned': st.scanned})
        if p == '/api/game/scanstate':
            st = games_store()
            with st.lock: return self.js({'running': st.running, 'done': st.done, 'total': st.total, 'error': st.error, 'scanned': st.scanned})
        if p == '/api/disk': return self.js(dict(zip(('total', 'used', 'free'), shutil.disk_usage(root('Video')))))
        if p == '/api/preview':
            r = dict(prev[qs['t']]); r['pages'] = r.get('pages', [])[int(qs.get('from', 0)):]; r['free'] = shutil.disk_usage(root('Video')).free; return self.js(r)
        if p == '/api/continue': return self.js(continue_items())
        mm = re.match(r'/sub/(\d+)/(\d+)\.vtt$', p)
        if mm:
            r = sql('select path,kind from items where id=?', (int(mm.group(1)),)); n = int(mm.group(2))
            fl = sub_files(r[0]['path']) if r and r[0]['kind'] in PLAY_KINDS else []
            if n >= len(fl) or fl[n][1].stat().st_size > SUB_MAX: return self.send_error(404)
            return self.blob(srt_to_vtt(decode_sub(fl[n][1].read_bytes())).encode('utf-8'), 'text/vtt; charset=utf-8')
        mm = re.match(r'/api/play/(\d+)$', p)
        if mm:
            st = play_state(int(mm.group(1)))
            return self.js(st) if st else self.js({'error': 'not found'}, 404)
        if p == '/api/library':
            q = '%' + qs.get('q', '') + '%'; k = qs.get('kind', '')
            out = []
            um = umeta_all()
            for r in sql("select i.* from items i left join usermeta u on u.item_id=i.id where (i.title like ? or i.author like ? or i.topic like ? or u.tags like ? or u.descr like ?) and (i.kind=? or ?='') order by i.id desc", (q, q, q, q, q, k, k)):
                d = dict(r); d['missing'] = not Path(r['path']).exists(); d['m'] = um.get(r['id']) or um_row(None); d['cover'] = cover_of(r, d['m']); d['extra'] = manga_extra(r)
                d['open'] = f"/s/{r['id']}/" + os.path.relpath(r['path'], r['root']).replace(os.sep, '/') if r['kind'] == 'site' else f"/m/{r['id']}" if r['kind'] == 'manga' else f"/p/{r['id']}" if r['kind'] in PLAY_KINDS else f"/f/{r['id']}"
                if r['kind'] == 'game': d['g'] = game_view(r); d['missing'] = False
                d['state'] = 'link' if r['kind'] == 'link' else ('missing' if d['missing'] else 'ok'); d['tracked'] = r['tracked'] or 0
                if r['kind'] == 'link': d['open'] = r['src'] or r['url']; d['missing'] = False
                out.append(d)
            return self.js(out)
        mm = re.match(r'/m/(\d+)$', p)
        if mm: return self.file(BASE / 'reader.html')
        if re.match(r'/p/\d+$', p): return self.file(BASE / 'player.html')
        mm = re.match(r'/api/manga/(\d+)$', p)
        if mm: return self.js(manga_info(int(mm.group(1))))
        mm = re.match(r'/mi/(\d+)/(\d+)/(\d{3}\.\w+)$', p)
        if mm:
            r = sql('select * from items where id=? and kind=?', (mm.group(1), 'manga'))
            return self.file(Path(r[0]['root']) / 'chapters' / mm.group(2) / mm.group(3)) if r else self.send_error(404)
        mm = re.match(r'/c/(\d+)$', p)
        if mm: c = umeta(int(mm.group(1)))['cover']; return self.file(c) if c else self.send_error(404)
        m = re.match(r'/([fst])/(\d+)(?:/(.*))?$', p)
        if m:
            r = sql('select * from items where id=?', (m.group(2),))
            if not r: return self.send_error(404)
            if m.group(1) == 'f': return self.file(r[0]['path'])
            if m.group(1) == 't': return self.file(r[0]['thumb'] or '')
            t = (Path(r[0]['root']) / m.group(3)).resolve()
            return self.file(t) if Path(r[0]['root']).resolve() in t.parents else self.send_error(403)
        self.send_error(404)
    def do_POST(self):
        if self.remote():
            if not self.gate('POST'): return
        elif not self.host_ok(): return self.send_error(403)
        if not self.remote() and self.path != '/ingest' and not self.path.startswith('/ext/'):  # управляющие запросы только из нашего окна (пользовательский заголовок не пропустит чужой сайт)
            o = self.headers.get('Origin')
            if self.headers.get('X-MH') != '1' or (o and urlparse(o).hostname not in ('127.0.0.1', 'localhost')): return self.send_error(403)
        try: self.post()
        except Exception as e: self.js({'error': str(e)}, 500)
    def post(self):
        if self.path == '/ingest': return self.ingest()
        if self.path.startswith('/ext/'): return self.ext_post()
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}'); p = self.path
        if p == '/api/add':
            urls = list(dict.fromkeys(x.strip() for x in d['urls'].splitlines() if x.strip().startswith('http')))
            if d['kind'] == 'site' and d.get('sel'): urls = [d['sel'][0] if not urls else urls[0]]
            for u in urls:
                enqueue({'sel': d.get('sel') or [], 'maxp': int(d.get('maxp') or cfg['maxp']), 'videos': bool(d.get('videos', cfg['videos'])), 'id': next(ids), 'url': u, 'kind': (manga_kind() if d['kind'] == 'mangaurl' else d['kind']), 'res': d.get('res') or cfg['res'], 'afmt': d.get('afmt') or cfg['afmt'], 'depth': int(d.get('depth', cfg['depth'])),
                         'topic': d.get('topic', '').strip(), 'subs': d['subs'] if 'subs' in d else (cfg['subs_langs'] if cfg['subs_on'] else ''), 'thumbs': bool(d.get('thumbs', cfg['thumbs'])), 'first': int(d.get('first') or 0), 'last': int(d.get('last') or 0), 'start_at': float(d.get('start_at') or 0),
                         'daily': bool(d.get('daily')), 'status': 'в очереди', 'pct': 0, 'title': u, 'speed': 0, 'eta': 0, 'cancel': False})
            return self.js({'added': len(urls)})
        if p == '/api/cancel':
            for j in jobs.values():
                if d.get('all') or j['id'] == d.get('id'):
                    j['cancel'] = True
                    if j['status'].startswith(('в очереди', 'запланировано')): j['status'] = 'отменено'
            return self.js({'ok': 1})
        if p == '/api/clear':
            for k in [k for k, j in jobs.items() if j['status'].startswith(('готово', 'отменено', 'ошибка', 'пропущено', 'сохранено', 'частично'))]: del jobs[k]
            return self.js({'ok': 1})
        if p == '/api/preview':
            tok = str(next(ids)); prev[tok] = {'done': 0, 'total': 0, 'size': 0, 'unknown': 0, 'skipped': 0, 'err': [], 'finished': False}
            threading.Thread(target=preview, args=(tok, d), daemon=True).start(); return self.js({'t': tok})
        if p == '/api/progress':
            r = sql('select url from items where id=?', (d['id'],))
            if r: sql('insert or replace into progress(slug,cid,page,updated) values(?,?,?,?)', (r[0]['url'][6:], str(d['cid']), int(d['page']), time.time()))
            return self.js({'ok': 1})
        if p == '/api/play/pos':
            if not isinstance(d.get('id'), int) or isinstance(d.get('id'), bool): return self.js({'error': 'bad id'}, 400)
            if not play_state(d['id']): return self.js({'error': 'not found'}, 404)
            try: return self.js({'ok': 1, 'saved': save_pos(d['id'], d.get('pos'), d.get('dur', 0))})
            except ValueError: return self.js({'error': 'bad numbers'}, 400)
        if p == '/api/play/forget':
            sql('delete from playpos where item_id=?', (d.get('id'),))
            r = sql('select url from items where id=? and kind=?', (d.get('id'), 'manga'))
            if r: sql('delete from progress where slug=?', (r[0]['url'][6:],))
            return self.js({'ok': 1})
        if p == '/api/discover':
            tok = str(next(ids)); prev[tok] = {'done': 0, 'total': 0, 'size': 0, 'unknown': 0, 'skipped': 0, 'err': [], 'finished': False, 'pages': []}
            threading.Thread(target=discover, args=(tok, d), daemon=True).start(); return self.js({'t': tok})
        if p == '/api/reveal':  # показать файл или папку материала в проводнике (путь берём только из библиотеки)
            r = sql('select * from items where id=?', (d.get('id'),))
            if not r or r[0]['kind'] == 'link': return self.js({'ok': False})
            t = r[0]['root'] if (r[0]['kind'] in ('manga', 'site') and r[0]['root']) else r[0]['path']
            import sys; sys.path.insert(0, str(BASE)); import gamesweep
            return self.js({'ok': bool(t and os.path.exists(t) and gamesweep.reveal(t))})
        if p == '/api/game/add':
            raw = d.get('urls') if isinstance(d.get('urls'), list) else re.split(r'\s+', str(d.get('url') or ''))
            urls = []
            for u in raw:
                u = str(u).strip()
                if u.startswith(('http://', 'https://')) and game_key(u) not in urls: urls.append(game_key(u))
            if not urls: return self.js({'error': 'нужна ссылка на тему игры'})
            return self.js({'job': new_job(urls[0] if len(urls) == 1 else 'games:add', 'gamecard', urls=urls, title=urls[0][:120] if len(urls) == 1 else f'Добавление игр: {len(urls)}'), 'count': len(urls)})
        if p == '/api/game/replace':
            if not d.get('confirm'): return self.js({'error': 'нужно подтверждение'})
            gids = [int(x) for x in d.get('ids', []) if str(x).isdigit()]
            if not gids: return self.js({'error': 'ничего не выбрано'})
            return self.js({'job': new_job('games:replace', 'gamereplace', ids=gids, delete_old=d.get('delete_old', True) is not False, title=f'Замена версий игр: {len(gids)}'), 'count': len(gids)})
        if p == '/api/game/rescan':   # найти скачанные игры заново (после новой загрузки)
            root_ = cfg.get('games_root') or ''
            if not root_ or not os.path.isdir(root_): return self.js({'error': 'Сначала укажите папку с играми в настройках'})
            return self.js({'started': bool(games_store().start_scan(root_, 'auto'))})
        if p == '/api/game/locate':   # «Проверить, скачана ли»: свежий поиск по каталогу + похожие папки для ручной привязки
            r_ = sql("select * from items where kind='game' and id=?", (d.get('id'),)); root_ = cfg.get('games_root') or ''
            if not r_: return self.js({'error': 'нет такой игры'})
            if not root_: return self.js({'error': 'Сначала укажите папку с играми в настройках'})
            if not os.path.isdir(root_): return self.js({'error': f'Папка с играми недоступна: {root_}. Проверьте, что диск подключён и путь в настройках верный'})
            import gamesweep
            games_ = gamesweep.list_games(root_, 'auto'); dl_ = bool(r_[0]['path'] and Path(r_[0]['path']).exists())
            found = gameupdate.candidates(r_[0]['title'], games_); started = bool(games_store().start_scan(root_, 'auto'))
            return self.js({'found': found, 'rescan': started, 'downloaded': dl_, 'why': [] if dl_ else gamelink.explain(r_[0]['title'], games_)['lines']})
        if p == '/api/game/link':     # привязать папку к карточке вручную (запоминается и переживает пересканирование); пустой path снимает привязку
            r_ = sql("select * from items where kind='game' and id=?", (d.get('id'),)); root_ = cfg.get('games_root') or ''; pth = str(d.get('path') or '')
            if not r_: return self.js({'error': 'нет такой игры'})
            if pth and not (gameupdate.inside(pth, root_) and os.path.exists(pth)): return self.js({'error': 'эта папка не в каталоге игр'})
            i_ = ginfo(r_[0])
            if pth:
                i_['pin'] = pth
                for o in sql("select * from items where kind='game' and id!=? and path=?", (r_[0]['id'], pth)):   # такая же установленная карточка без данных с сайта: сливаем
                    if not ginfo(o).get('meta'): sql('delete from items where id=?', (o['id'],))
            else:
                old_ = i_.pop('pin', None)
                if old_:   # отвязали: забываем связь и убираем свой маркер, иначе он вернёт папку к карточке
                    sql('delete from links where path=?', (os.path.abspath(old_),)); m_ = gamelink.read_marker(old_); th_ = (i_.get('meta') or {}).get('thread') or ''
                    if m_ and ((th_ and m_['thread'] == th_) or m_['key'] == (str(r_[0]['url'])[5:] if str(r_[0]['url']).startswith('game:') else name_key(r_[0]['title']))): gamelink.remove_marker(old_)
            ginfo_save(r_[0]['id'], i_); games_scan(root_); return self.js({'ok': 1})
        if p == '/api/game/check':
            gids = [d['id']] if d.get('id') else None     # не «ids»: так называется глобальный счётчик заданий, и присваивание ломало /api/add
            return self.js({'job': new_job('games:check', 'gamecheck', ids=gids, title='Проверка игр')})
        if p == '/api/game/set':
            r = sql("select * from items where id=? and kind='game'", (d.get('id'),))
            if r:
                i = ginfo(r[0])
                if 'auto' in d: i['auto'] = bool(d['auto'])
                if 'note' in d: i['note'] = str(d['note'])[:2000]
                ginfo_save(r[0]['id'], i)
            return self.js({'ok': 1})
        if p == '/api/inbox/confirm': return self.js(inbox_confirm(d))
        if p == '/api/inbox/dismiss':
            if not sql("select 1 from inbox where batch=? and status in ('pending','queued','closing')", (d['batch'],)): sql('delete from inbox where batch=?', (d['batch'],))
            return self.js({'ok': 1})
        if p == '/api/inbox/reopened': sql("update inbox set status='reopened' where id=? and status='closed'", (d['id'],)); return self.js({'ok': 1})
        if p == '/api/ext/approve':
            o = d.get('origin')
            if o in PAIR:
                PAIR.pop(o)
                if d.get('allow'): EXT[o] = secrets.token_urlsafe(24); ext_save()
            return self.js({'ok': 1})
        if p == '/api/ext/forget': EXT.pop(d.get('origin'), None); ext_save(); return self.js({'ok': 1})
        if p == '/api/item/download':
            r = sql('select * from items where id=?', (d['id'],))[0]; src = r['src'] or r['url']; c = classify(src); jk = JOBK.get(c['kind'])
            if jk == 'mangaurl': jk = manga_kind()
            if not jk or c['kind'] == 'unknown': return self.js({'error': 'Для этого источника скачивание пока недоступно'})
            return self.js({'job': new_job(c.get('norm') or src, jk, title=r['title'])})
        if p == '/api/scan': scan(); threading.Thread(target=backfill, daemon=True).start(); return self.js({'ok': 1})
        if p == '/api/meta/set':
            if not sql('select 1 from items where id=?', (d.get('id'),)): return self.js({'error': 'нет такой записи'})
            try: return self.js({'meta': umeta_set(int(d['id']), d)})
            except (ValueError, TypeError): return self.js({'error': 'оценка: число от 0 до 10'})
        if p == '/api/cover/set':    # своя обложка (картинка с вашего компьютера): хранится отдельно, обновление темы её не затирает
            r = sql('select * from items where id=?', (d.get('id'),)); m = re.match(r'data:image/[a-z+.-]+;base64,(.+)$', str(d.get('data') or ''), re.S)
            if not r: return self.js({'error': 'нет такой записи'})
            try: data = base64.b64decode(m.group(1)) if m else b''
            except Exception: data = b''
            e = sniff(data)
            if not e or len(data) > 6_000_000: return self.js({'error': 'нужна картинка JPG, PNG, WebP или GIF до 6 МБ'})
            dd = BASE / 'covers'; dd.mkdir(exist_ok=True); old = umeta(r[0]['id'])['cover']; f = dd / f"u{r[0]['id']}-{int(time.time())}.{e}"; f.write_bytes(data)
            if old and Path(old).parent == dd and Path(old) != f: Path(old).unlink(missing_ok=True)
            umeta_set(r[0]['id'], {'cover': str(f)}); return self.js({'cover': cover_of(r[0])})
        if p == '/api/cover/clear':
            r = sql('select * from items where id=?', (d.get('id'),))
            if not r: return self.js({'error': 'нет такой записи'})
            old = umeta(r[0]['id'])['cover']
            if old and Path(old).parent == BASE / 'covers': Path(old).unlink(missing_ok=True)
            umeta_set(r[0]['id'], {'cover': ''}); return self.js({'cover': cover_of(r[0])})
        if p == '/api/edit':
            r = sql('select * from items where id=?', (d['id'],))[0]; path = r['path']; au = d['author'].strip() or r['author']
            if r['kind'] not in ('site', 'manga', 'link', 'game') and path and au != r['author'] and Path(path).exists():
                src = Path(path); dst = src.parent.parent / safe(au); dst.mkdir(parents=True, exist_ok=True)
                for f in list(src.parent.iterdir()):
                    if f.stem == src.stem or f.name.startswith(src.stem + '.'): shutil.move(str(f), str(dst / f.name))
                path = str(dst / src.name)
            sql('update items set author=?, topic=?, path=?, thumb=? where id=?', (au, d['topic'].strip() or r['topic'], path, r['thumb'] if r['kind'] in ('site', 'manga', 'link', 'game') else thumb_of(path), d['id']))
            return self.js({'ok': 1})
        if p == '/api/delete':
            r = sql('select * from items where id=?', (d['id'],))
            if r and d.get('files') and r[0]['kind'] not in ('link', 'game') and r[0]['path']:
                try:
                    if r[0]['root']: shutil.rmtree(r[0]['root'])
                    else:
                        s = Path(r[0]['path'])
                        for f in list(s.parent.iterdir()):
                            if f.stem == s.stem or f.name.startswith(s.stem + '.'): f.unlink()
                except OSError: pass
            old = umeta(int(d['id']))['cover']
            if old and Path(old).parent == BASE / 'covers': Path(old).unlink(missing_ok=True)
            sql('delete from items where id=?', (d['id'],)); sql('delete from playpos where item_id=?', (d['id'],)); sql('delete from usermeta where item_id=?', (d['id'],)); return self.js({'ok': 1})
        if p == '/api/lan/logout': return self.js({'ok': 1, 'closed': SESS.clear()})   # выйти на всех устройствах
        if p == '/api/feed/seen':   # отметить прочитанным: выбранные события, весь вид или всё
            ids_ = [int(x) for x in d.get('ids', []) if str(x).isdigit()]
            if ids_: sql(f"update feed set seen=1 where id in ({','.join('?' * len(ids_))})", ids_)
            elif d.get('kind') in feedlib.KINDS: sql('update feed set seen=1 where kind=?', (d['kind'],))
            elif d.get('all'): sql('update feed set seen=1')
            return self.js({'ok': 1})
        if p == '/api/feed/dismiss':
            ids_ = [int(x) for x in d.get('ids', []) if str(x).isdigit()]
            if ids_: sql(f"delete from feed where id in ({','.join('?' * len(ids_))})", ids_)
            return self.js({'ok': 1})
        if p == '/api/feed/check':
            if any(j['kind'] == 'feedcheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()): return self.js({'error': 'Проверка уже идёт'}, 409)
            return self.js({'job': new_job('feed:manual', 'feedcheck', title='Лента: проверка источников', kinds=[k for k in d.get('kinds', []) if k in feedlib.KINDS] or list(feedlib.KINDS))})
        if p == '/api/feed/act': res_, code_ = feed_act(int(d.get('id') or 0)); return self.js(res_, code_)
        if p == '/api/feed/watch':   # канал или плейлист для слежения; первая проверка только запомнит, что уже есть
            u_ = str(d.get('url') or '').strip()
            if not u_.startswith(('http://', 'https://')): return self.js({'error': 'Нужна ссылка на канал или плейлист (http…)'}, 400)
            try: guard_literal(u_)
            except Exception: return self.js({'error': 'Эта ссылка не подходит'}, 400)
            if sql('select 1 from watch where url=?', (u_,)): return self.js({'error': 'Этот источник уже отслеживается'}, 409)
            sql('insert into watch(url,title,added) values(?,?,?)', (u_, str(d.get('title') or '').strip()[:120], time.time())); return self.js({'ok': 1})
        if p == '/api/feed/unwatch': sql('delete from watch where id=?', (int(d.get('id') or 0),)); return self.js({'ok': 1})
        if p == '/api/versions/scan':   # «Версии и чистка»: просмотреть папку игр заново
            root_ = str(d.get('root') or cfg.get('games_root') or '').strip()
            if not os.path.isdir(root_): return self.js({'error': f'Папка не найдена: {root_}' if root_ else 'Укажите папку с играми'}, 400)
            if root_ != cfg.get('games_root'): cfg['games_root'] = root_; CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), 'utf-8')   # одна папка игр на всё приложение
            return self.js({'started': bool(games_store().start_scan(root_, d.get('layout') if d.get('layout') in ('auto', 'flat', 'nested') else 'auto'))})
        if p == '/api/versions/saves': return self.js(games_store().saves([str(x) for x in d.get('paths', [])]))
        if p == '/api/versions/tabs':   # сравнить вставленный список вкладок с играми на ПК
            r_ = games_store().analyze(str(d.get('text', '')))
            return self.js(r_) if r_ is not None else self.js({'error': 'Сначала просканируйте папку с играми (вкладка «Версии»).'}, 409)
        if p == '/api/versions/trash':   # сервер сам решает, что можно удалить: клиенту не доверяем
            st_ = games_store(); mode = d.get('saves') if d.get('saves') in ('copy', 'ignore', 'skip') else 'skip'
            res_ = st_.trash([str(x) for x in d.get('paths', [])], mode, bool(d.get('force'))); return self.js({'results': res_, 'state': st_.snapshot()})
        if p == '/api/versions/reveal': return self.js({'ok': games_store().reveal(str(d.get('path') or ''))})
        if p == '/api/settings':
            if 'lan_pin' in d:   # PIN хранится только хэшем
                err = lan.valid_pin(str(d['lan_pin']))
                if err: return self.js({'error': err}, 400)
                cfg['lan_pin_salt'], cfg['lan_pin_hash'] = lan.hash_pin(str(d['lan_pin'])); SESS.clear()
            if d.get('lan') and not cfg.get('lan_pin_hash'): return self.js({'error': 'Сначала задайте PIN: без него доступ с других устройств не включается'}, 400)
            if 'lan' in d: cfg['lan'] = bool(d['lan'])
            old_gr = cfg.get('games_root'); cfg.update({k: d[k] for k in ('folder', 'skip', 'cookie_file', 'cookie_browser', 'games_root', 'show_browser', 'browser', 'limit_mb', 'workers', 'res', 'afmt', 'subs_on', 'subs_langs', 'thumbs', 'depth', 'maxp', 'videos', 'manga_via', 'games_check_hours', 'game_marker', 'feed_hours') if k in d}); _op[0] = None; spawn_workers()
            if cfg.get('games_root') and cfg['games_root'] != old_gr: threading.Thread(target=games_scan, args=(cfg['games_root'],), daemon=True).start()
            CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), 'utf-8'); return self.js(cfg_public())
        self.send_error(404)

if __name__ == '__main__':
    scan(); threading.Thread(target=backfill, daemon=True).start()
    spawn_workers(); threading.Thread(target=settle_loop, daemon=True).start(); threading.Thread(target=game_auto_loop, daemon=True).start(); threading.Thread(target=feed_auto_loop, daemon=True).start()
    if cfg.get('games_root'): threading.Thread(target=games_scan, args=(cfg['games_root'],), daemon=True).start()
    PORT = int(os.environ.get('MEDIAHUB_PORT', 8765)); print(f'MediaHub: http://127.0.0.1:{PORT}')
    LAN_BOUND = bool(cfg.get('lan') or os.environ.get('MEDIAHUB_LAN')) and bool(cfg.get('lan_pin_hash'))   # без PIN сеть не открываем
    if LAN_BOUND: print('Доступ с других устройств включён (нужен PIN): ' + ', '.join(f'http://{a}:{PORT}' for a in lan.local_addresses()))
    if not os.environ.get('MEDIAHUB_NO_BROWSER'): webbrowser.open(f'http://127.0.0.1:{PORT}')
    ThreadingHTTPServer(('0.0.0.0' if LAN_BOUND else '127.0.0.1', PORT), H).serve_forever()
