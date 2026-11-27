/* Shared confirmed credits; editing uses the owner's loopback save service. */
(function () {
  'use strict';
  let registry = {revision: 0, records: {}}, loaded = false, editing = false, busy = false;
  const grid = document.getElementById('grid');
  const canEdit = window.boardManageMode;
  const panel = document.createElement('div');
  panel.className = 'author-panel';
  panel.innerHTML = '<strong id="author-title"></strong><p id="author-note"></p>' +
    (canEdit ? '<button type="button" id="author-edit">标记作者</button>' +
    '<form id="author-form" hidden><label for="author-name">作者署名</label>' +
    '<input id="author-name" maxlength="80" autocomplete="off" required>' +
    '<button type="submit" id="author-save">确定并同步</button>' +
    '<button type="button" id="author-cancel">取消</button></form>' +
    '<p id="author-message" role="status" aria-live="polite"></p>' : '');
  document.getElementById('m-src').before(panel);
  const title = panel.querySelector('#author-title'), note = panel.querySelector('#author-note');
  const edit = panel.querySelector('#author-edit'), form = panel.querySelector('form');
  const input = panel.querySelector('input'), save = panel.querySelector('#author-save');
  const message = panel.querySelector('#author-message');
  const current = () => (window.SUBLIB?.versions || {})[document.getElementById('m-title').dataset.code || document.getElementById('m-title').textContent];
  const credit = v => registry.records[v.code + '@' + v.sha256];
  const confirmed = v => credit(v)?.status === 'confirmed' && !!credit(v)?.author;
  function paint() {
    grid.querySelectorAll('.card2').forEach(card => {
      const v = (window.SUBLIB?.versions || {})[card.querySelector('img.pv')?.alt];
      if (!v) return;
      let badge = card.querySelector('.author-badge');
      if (!badge) { badge = document.createElement('div'); card.querySelector('.cp').prepend(badge); }
      badge.className = 'author-badge' + (confirmed(v) ? ' confirmed' : ' pending');
      badge.textContent = confirmed(v) ? '作者 · ' + credit(v).author : (loaded ? '作者待确认' : '正在读取作者…');
    });
    const v = current();
    if (!v) return;
    title.textContent = confirmed(v) ? '作者：' + credit(v).author + ' ✓ 已确定' : (loaded ? '作者待确认' : '正在读取作者…');
    note.textContent = confirmed(v) ? '确认于 ' + credit(v).confirmed_at.replace('T', ' ') :
      '此版本尚未确认署名。';
    if (edit) edit.textContent = confirmed(v) ? '修改署名' : '标记作者';
  }
  async function publicRead() {
    try {
      const response = await fetch('authors.json?t=' + Date.now(), {cache: 'no-store'});
      if (!response.ok) throw Error();
      const next = await response.json();
      if (!editing && next.revision >= registry.revision) registry = next;
      loaded = true; paint();
    } catch (_) {
      if (!loaded) { note.textContent = '署名记录读取失败，请刷新重试。'; }
    }
  }
  async function local(path, body) {
    const response = await fetch('/' + path, {
      method: body ? 'POST' : 'GET', cache: 'no-store', signal: AbortSignal.timeout(body ? 180000 : 7000),
      headers: body ? {'Content-Type': 'application/json', 'X-Author-Confirm': '1'} : {},
      ...(body ? {body: JSON.stringify(body)} : {})
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '保存失败');
    return result;
  }
  if (edit) edit.onclick = async function () {
    const v = current(); if (!v || busy) return;
    edit.disabled = true; message.textContent = '连接本机署名保存服务…';
    try {
      const next = await local('authors');
      if (current()?.code !== v.code) return;
      if (next.revision < registry.revision) throw Error('本机记录落后于线上，请先同步本机资源库再编辑。');
      registry = next; loaded = true; editing = true; paint();
      input.value = credit(v)?.author || ''; form.hidden = false; edit.hidden = true;
      message.textContent = '填写后点击确定。署名将公开展示，并用于这个版本以后的出包。';
      input.focus();
    } catch (e) {
      message.textContent = e.message === 'Failed to fetch' || e.name === 'TimeoutError' ?
        '无法连接本机管理服务，请重试。' : e.message;
    } finally { edit.disabled = false; }
  };
  if (form) form.onsubmit = async function (event) {
    event.preventDefault(); const v = current(); const author = input.value.trim();
    if (!v || busy || !author) return;
    if (!window.confirm('确定将 ' + v.code + ' 的作者署名定为“' + author + '”？\n以后这个版本的出包将使用此署名。')) return;
    busy = true; save.disabled = true; input.disabled = true;
    message.textContent = '正在保存并同步，请稍候…';
    try {
      const result = await local('confirm', {code: v.code, sha256: v.sha256, author, revision: registry.revision});
      registry = result.registry; loaded = true;
      message.textContent = result.message;
      if (result.published) { editing = false; form.hidden = true; edit.hidden = false; }
      paint();
    } catch (e) { message.textContent = e.message || '保存失败，请重试。'; }
    finally { busy = false; save.disabled = false; input.disabled = false; }
  };
  if (form) panel.querySelector('#author-cancel').onclick = function () {
    if (busy) return;
    editing = false; form.hidden = true; edit.hidden = false; message.textContent = ''; paint();
  };
  new MutationObserver(paint).observe(grid, {childList: true});
  new MutationObserver(function () {
    if (form) { editing = false; form.hidden = true; edit.hidden = false; message.textContent = ''; }
    paint();
  }).observe(document.getElementById('m-title'), {childList: true});
  paint(); publicRead(); setInterval(publicRead, 15000);
})();
