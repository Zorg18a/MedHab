// Грубое определение типа страницы для подписей на кнопках; окончательно тип решает приложение.
// Список сайтов приходит из sites.js (генерируется из sites.json), YouTube разбирается здесь: он зависит от параметров адреса.
globalThis.kindOf = function kindOf(url) {
  let u; try { u = new URL(url); } catch (e) { return 'other'; }
  const h = u.hostname.toLowerCase().replace(/^www\./, ''), p = u.pathname;
  if (h === 'music.youtube.com') return 'audio';
  if (h === 'youtu.be' || ((h === 'youtube.com' || h === 'm.youtube.com') && (u.searchParams.get('v') || p === '/playlist' || /^\/(@|channel|c|user)/.test(p)))) return 'video';
  for (const s of globalThis.MH_SITES || []) {
    if ((s.hosts.includes(h) || (s.suffixes || []).some(x => h.endsWith(x))) && (!s.path || new RegExp(s.path).test(p))) return s.kind;
  }
  return 'other';
};
