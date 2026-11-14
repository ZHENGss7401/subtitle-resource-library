/* Group-first member editing. Drafts stay separate from the published config. */
window.createGroupManager = function (options) {
  'use strict';
  const get = id => document.getElementById(id);
  const dialog = get('group-manager'), editor = get('manage-editor');
  const status = get('manage-status'), search = get('manage-search');
  const save = get('manage-save'), retry = get('manage-retry');
  let draft, dirty = false, busy = false, active = 'basic', adding = false;
  const selected = new Set();
  const local = location.origin === 'http://127.0.0.1:17843';
  const clone = value => JSON.parse(JSON.stringify(value));
  const versions = () => options.getData().versions;
  const codes = key => key === 'q33'
    ? Object.keys(versions()).filter(code => /^Q33(?:$|-)/i.test(code))
    : draft.groups[key].codes;
  const name = () => active === 'q33' ? 'Q33俱乐部' : draft.groups[active].name;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function changed() {
    dirty = true;
    status.textContent = '有未保存的修改';
  }
  function paint() {
    get('manage-tabs').querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.group === active));
      button.querySelector('.count').textContent = codes(button.dataset.group).length;
    });
    get('manage-heading').textContent = adding ? '添加到' + name() : name() + ' · ' + codes(active).length + ' 个版本';
    const add = get('manage-add');
    add.hidden = active === 'q33';
    add.textContent = adding ? '返回组内成员' : '＋ 添加版本';
    get('manage-auto').hidden = active !== 'q33';
    search.placeholder = adding ? '搜索要添加的版号' : '搜索组内版号';
    search.setAttribute('aria-label', search.placeholder);
    save.textContent = adding ? '添加所选' + (selected.size ? '（' + selected.size + '）' : '') : '保存更改';
    save.disabled = busy || (adding ? !selected.size : !dirty);
    retry.disabled = busy;
    const target = get('manage-list');
    target.replaceChildren();
    const term = search.value.trim().toUpperCase();
    const candidates = (adding ? Object.keys(versions()).filter(code => !codes(active).includes(code)) : codes(active))
      .filter(code => versions()[code] && [code].concat(versions()[code].aliases || []).join(' ').toUpperCase().includes(term))
      .sort((a, b) => a.localeCompare(b, undefined, {numeric: true}));
    candidates.forEach(code => {
      const card = element(adding ? 'button' : 'article', 'member-card' + (adding ? ' member-pick' : ''));
      const image = element('img');
      image.src = versions()[code].preview_rel;
      image.alt = code;
      image.loading = 'lazy';
      card.appendChild(image);
      const info = element('div', 'member-info');
      info.appendChild(element('span', 'member-code', code));
      if (adding) {
        card.type = 'button';
        card.setAttribute('aria-label', '选择 ' + code);
        card.setAttribute('aria-pressed', String(selected.has(code)));
        card.appendChild(element('span', 'member-check', selected.has(code) ? '✓' : ''));
        card.addEventListener('click', () => {
          if (selected.has(code)) selected.delete(code); else selected.add(code);
          // Keep focus and scroll position when picking several images.
          card.setAttribute('aria-pressed', String(selected.has(code)));
          card.querySelector('.member-check').textContent = selected.has(code) ? '✓' : '';
          save.textContent = '添加所选' + (selected.size ? '（' + selected.size + '）' : '');
          save.disabled = !selected.size || busy;
        });
      } else if (active !== 'q33') {
        const remove = element('button', 'member-remove', '移出此组');
        remove.type = 'button';
        remove.setAttribute('aria-label', '将 ' + code + ' 移出' + name());
        remove.addEventListener('click', () => {
          draft.groups[active].codes = codes(active).filter(value => value !== code);
          changed();
          paint();
        });
        info.appendChild(remove);
      }
      card.appendChild(info);
      target.appendChild(card);
    });
    if (!candidates.length) target.appendChild(element('div', 'manager-empty',
      term ? '没有找到这个版本，试试其他版号。' : adding ? '所有版本都已在这个分组中。' : '这个分组还没有成员，点击“添加版本”开始整理。'));
  }
  async function call(method, body) {
    let response;
    try {
      response = await fetch('http://127.0.0.1:17843/groups', {
        method, headers: body ? {'Content-Type': 'application/json', 'X-Author-Confirm': '1'} : {},
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(body ? 90000 : 7000)
      });
    } catch (_) {
      throw Error(local ? '暂时无法连接保存服务，请重试。未保存的修改仍保留在此窗口。'
        : '请打开下方的本机管理页进行保存。');
    }
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '保存失败，请重试。');
    return result;
  }
  async function connect() {
    if (busy) return;
    busy = true;
    status.textContent = '正在连接…';
    paint();
    try {
      const next = await call('GET');
      if (dirty && next.revision !== draft.revision) {
        status.textContent = '分组已被其他操作更新，请刷新后按最新成员重新调整。当前修改仍保留。';
      } else {
        if (!dirty) draft = clone(next);
        status.textContent = dirty ? '有未保存的修改' : '选择分组，查看和整理成员';
      }
      retry.hidden = true;
      get('local-manage-help').hidden = true;
    } catch (error) {
      status.textContent = error.message;
      retry.hidden = false;
      get('local-manage-help').hidden = local;
    } finally {
      busy = false;
      paint();
    }
  }
  get('manage-open').addEventListener('click', () => {
    if (!draft || !dirty) {
      draft = clone(options.getConfig());
      const current = options.getGroup();
      active = ['basic', 'extra', 'q33'].includes(current) ? current : 'basic';
      adding = false;
      selected.clear();
      search.value = '';
    }
    dialog.showModal();
    paint();
    connect();
  });
  get('manage-tabs').addEventListener('click', event => {
    const button = event.target.closest('button[data-group]');
    if (!button) return;
    active = button.dataset.group;
    adding = false;
    selected.clear();
    search.value = '';
    paint();
  });
  get('manage-add').addEventListener('click', () => {
    adding = !adding;
    selected.clear();
    search.value = '';
    paint();
    if (adding) search.focus();
  });
  search.addEventListener('input', paint);
  retry.addEventListener('click', connect);
  save.addEventListener('click', async () => {
    if (busy) return;
    if (adding) {
      draft.groups[active].codes = [...new Set(codes(active).concat([...selected]))];
      selected.clear();
      adding = false;
      search.value = '';
      changed();
      paint();
      return;
    }
    busy = true;
    editor.disabled = true;
    status.textContent = '正在保存并同步…';
    paint();
    try {
      const result = await call('POST', {revision: draft.revision, groups: {
        basic: draft.groups.basic.codes, extra: draft.groups.extra.codes
      }});
      draft = clone(result.config);
      dirty = false;
      options.onSave(result.config);
      status.textContent = result.message;
    } catch (error) {
      status.textContent = error.message;
      retry.hidden = false;
      get('local-manage-help').hidden = local;
    } finally {
      busy = false;
      editor.disabled = false;
      paint();
    }
  });
};
