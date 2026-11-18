// No dependencies or server: execute each page's actual inline controller in a minimal DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.events = {}; this.dataset = {}; this.style = {}; this.value = ''; this.hidden = false; this.className = ''; this._text = ''; }
  get classList() { return {contains: x => this.className.split(' ').includes(x), add: x => { if (!this.classList.contains(x)) this.className += ' ' + x; }, remove: x => { this.className = this.className.split(' ').filter(y => y !== x).join(' '); }, toggle: (x, yes) => yes ? this.classList.add(x) : this.classList.remove(x)}; }
  set textContent(x) { this._text = x; this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set innerHTML(x) { this._html = x; this.children = []; }
  get innerHTML() { return this._html || ''; }
  appendChild(x) { x.parent = this; this.children.push(x); return x; }
  after(x) { this.parent.appendChild(x); }
  remove() { this.parent.children = this.parent.children.filter(x => x !== this); }
  setAttribute(k, v) { this[k] = v; }
  getAttribute(k) { return this[k]; }
  removeAttribute(k) { delete this[k]; }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  fire(k, extra = {}) { for (const fn of this.events[k] || []) fn.call(this, {target: this, stopPropagation() {}, preventDefault() {}, ...extra}); }
  querySelector(s) { return this.querySelectorAll(s)[0] || null; }
  querySelectorAll(s) { const match = e => s.startsWith('.') ? s.slice(1).split('.').every(c => e.classList.contains(c)) : e.tagName === s; return this.children.flatMap(e => [ ...(match(e) ? [e] : []), ...e.querySelectorAll(s)]); }
  pause() {} load() {} play() { return Promise.resolve(); }
}
const codes = ['Q33-2-2', 'Q33-13-2', 'Q33-16', 'Q33-17', 'Q33-17-2', 'Q33-18', 'Q33-19', 'Q33-15', 'Q33-口臭B1'];
function version(code, extra = {}) { return {code, display_name: '显示 ' + code, confidence: '已证实', size: [750, 1334], sha256: code.repeat(20), preview_rel: code + '-preview.png', layer_rel: code + '.png', copy: {source: code + '.doc', lines: [code + ' copy']}, ...extra}; }
function boot(file, versions) {
  const html = fs.readFileSync(path.join(__dirname, file), 'utf8');
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Element()]));
  nodes.modal.className = 'hidden'; nodes['m-video'].hidden = true;
  const pic = new Element(); pic.className = 'fcard pic'; const header = pic.appendChild(new Element('header')); header.appendChild(nodes['m-title']);
  const filters = ['all', 'q33', 'basic', 'extra'].map(group => { const e = new Element('button'); e.dataset.group = group; return e; });
  const document = {documentElement: new Element(), body: new Element(), head: new Element(), getElementById: id => nodes[id], createElement: t => new Element(t), createTextNode: t => {const e = new Element(); e.textContent = t; return e;}, querySelectorAll: s => s.includes('.filter-btn') ? filters : [], querySelector: s => s === '.fcard.pic' ? pic : s.includes('.variant-select') ? pic.querySelector('.variant-select') : null, addEventListener() {}};
  const context = {document, URLSearchParams, location: {search: '', origin: 'https://example.test'}, setTimeout() {}, setInterval() {}, fetch: () => new Promise(() => {}), getComputedStyle: () => ({height: '600'}), console};
  context.window = {SUBLIB: {versions}, innerWidth: 800, addEventListener() {}, createGroupManager() {}};
  let script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
  script = script.replace('  render(); loadConfig();', '  window.test={render,openModal,setImg,lbOpen,getList:function(){return list;},setConfig:function(x){cfg=x;}}; render(); loadConfig();');
  vm.runInNewContext(script, context, {filename: file});
  return {nodes, pic, filters, api: context.window.test, data: context.window.SUBLIB, script};
}
for (const file of ['index.html', 'page.html']) {
  const versions = {};
  for (const code of codes) { versions[code] = version(code); versions[code + '黑'] = version(code + '黑', {board_parent_code: code, variant_label: '黑底白字标题'}); }
  versions.A1 = version('A1'); versions.Orphan = version('Orphan', {board_parent_code: 'Missing'});
  versions.MOV = version('MOV', {asset_type: 'dynamic_video', preview_video_rel: 'movie.mp4', layer_rel: 'movie.mov'});
  const before = JSON.stringify(versions), {nodes, pic, filters, api, data} = boot(file, versions);
  assert.equal(api.getList().length, 12); assert.equal(nodes.grid.children.length, 12);
  assert.equal(nodes.stat.textContent, '12 / 12 组 · 21 / 21 个版本');
  assert.match(nodes.h2sub.innerHTML, /12<\/b> 组、<b>21/);
  api.setConfig({groups: {basic: {codes: ['Q33-16黑']}}, dates: {}, notes: {}});
  filters[2].fire('click'); assert.equal(api.getList().length, 1); assert.equal(api.getList()[0].code, 'Q33-16');
  filters[1].fire('click'); assert.equal(api.getList().length, 9); assert.match(nodes.stat.textContent, /9 \/ 12 组 · 18 \/ 21/);
  for (const code of codes) {
    nodes.q.value = code + '黑'; nodes.q.fire('input');
    assert.equal(api.getList().length, 1); assert.equal(api.getList()[0].code, code + '黑');
    let card = nodes.grid.children[0]; assert.equal(card.dataset.parentCode, code);
    let select = card.querySelector('select'); assert.equal(select.children[0].textContent, '白底黑字标题 · ' + code);
    select.value = code; select.fire('change'); assert.equal(api.getList()[0].code, code);
    card = nodes.grid.children[0]; card.fire('click'); assert.equal(nodes['m-title'].dataset.code, code);
    select = pic.querySelector('select'); select.value = code + '黑'; select.fire('change');
    assert.equal(nodes['m-title'].dataset.code, code + '黑'); assert.match(nodes['m-title'].textContent, new RegExp(code + '黑'));
    assert.equal(nodes['m-img'].src, code + '黑-preview.png'); assert.equal(nodes['m-text'].textContent, code + '黑 copy');
    assert.match(nodes['m-src'].textContent, /黑\.doc/); assert.equal(nodes['m-download'].href, code + '黑.png'); assert.equal(nodes['m-download'].hidden, false);
    api.setImg('layer'); assert.equal(nodes['m-img'].src, code + '黑.png'); api.lbOpen(0); assert.equal(nodes.lbimg.src, code + '黑.png');
  }
  nodes.q.value = ''; nodes.q.fire('input'); filters[0].fire('click');
  api.openModal(versions.A1); assert.equal(pic.querySelector('select'), null); assert.equal(nodes['m-download'].hidden, true);
  api.openModal(versions.MOV); assert.equal(nodes['m-video'].src, 'movie.mp4'); assert.equal(nodes['m-download'].href, 'movie.mov');
  assert.equal(data.versions, versions); assert.equal(JSON.stringify(versions), before, 'raw versions must not be mutated');
  // Read-only smoke test against the current publication data, including any concurrently added variants.
  const actualContext = {window: {}}; vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'data.js'), 'utf8'), actualContext);
  const actual = actualContext.window.SUBLIB.versions, live = boot(file, actual);
  const expected = new Set(Object.values(actual).map(v => v.board_parent_code && actual[v.board_parent_code] ? v.board_parent_code : v.code)).size;
  assert.equal(live.api.getList().length, expected);
  console.log(`${file}: PASS (nine pairs, search, Q33/custom filter, selectors, current code, copy, PNG/MOV, lightbox, unparented/orphan, immutability); live ${expected} groups / ${Object.keys(actual).length} versions`);
}
