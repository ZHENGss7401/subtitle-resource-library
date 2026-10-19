"""Confirmed authors are scoped to an exact version and locked PNG digest."""
import json
from pathlib import Path

LIBRARY = Path(r'Y:\足贴视频素材\BOREAC淋巴滴剂\0. 字幕资源库')

def require_author(code, sha256, library=LIBRARY):
    registry = json.loads((Path(library) / 'authors.json').read_text(encoding='utf-8'))
    records = registry.get('records', {})
    matches = [r for r in records.values() if r.get('sha256') == sha256 and r.get('status') == 'confirmed']
    if code:
        matches = [r for r in matches if r.get('code') == code]
    if len(matches) != 1 or not matches[0].get('author', '').strip():
        raise ValueError('作者待确认：请询问惠跃主人“这个新版的作者是谁？”，在资源库看板填写署名并点击确定后再出包。版本：%s' % (code or sha256[:12]))
    return dict(matches[0])

def write_credit(package, record):
    package = Path(package)
    package.mkdir(parents=True, exist_ok=True)
    (package / '作者署名.txt').write_text('作者：%s\n版本：%s\n确认时间：%s\n定版 SHA256：%s\n' % (
        record['author'], record['code'], record['confirmed_at'], record['sha256']), encoding='utf-8')
    agent = package / 'agent夹'
    agent.mkdir(exist_ok=True)
    (agent / '_作者署名.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
