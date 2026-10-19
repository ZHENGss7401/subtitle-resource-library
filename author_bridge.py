"""Loopback-only author confirmation service; no credentials reach the browser."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parent
LIB = Path(r'Y:\足贴视频素材\BOREAC淋巴滴剂\0. 字幕资源库')
ORIGINS = {'https://zhengss7401.github.io', 'http://127.0.0.1:17843'}
LOCK = threading.Lock()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def atomic(path, data):
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)

def git(*args):
    p = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True,
                       text=True, encoding='utf-8', timeout=45,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if p.returncode:
        raise RuntimeError('署名已保存，本次线上同步失败，请重试。')
    return p.stdout.strip()

def confirm(payload):
    code, sha = payload.get('code'), payload.get('sha256')
    author = payload.get('author')
    if not isinstance(author, str) or not author.strip() or len(author.strip()) > 80 or any(ord(c) < 32 for c in author):
        raise ValueError('请填写 1～80 字作者署名，不可包含换行。')
    for index in (LIB / 'INDEX.json', REPO / 'INDEX.json'):
        entry = read(index).get('versions', {}).get(code)
        if not entry or entry.get('sha256') != sha:
            raise ValueError('版本图片已变化或尚未上线，请刷新资源库后重新确认作者。')
    data = read(LIB / 'authors.json')
    if payload.get('revision') != data['revision']:
        raise ValueError('署名已被更新，请刷新后核对最新作者再操作。')
    # Pull only before a new edit. Pending local confirmation survives network failure.
    try:
        git('pull', '--ff-only')
        remote = read(REPO / 'authors.json')
        if remote['revision'] > data['revision']:
            atomic(LIB / 'authors.json', remote)
            raise ValueError('线上署名已更新，请刷新后重试。')
    except RuntimeError:
        pass
    key = code + '@' + sha
    old = data['records'].get(key)
    if not old or old['author'] != author.strip():
        record = {'code': code, 'sha256': sha, 'author': author.strip(), 'status': 'confirmed',
                  'confirmed_at': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
                  'confirmed_by': '惠跃主人', 'revision': data['revision'] + 1}
        data['history'].append({'previous': old, 'confirmed': record})
        data['records'][key] = record
        data['revision'] += 1
        atomic(LIB / 'authors.json', data)
    atomic(REPO / 'authors.json', data)
    try:
        git('add', '--', 'authors.json')
        if git('diff', '--cached', '--name-only', '--', 'authors.json'):
            git('commit', '--only', '-m', 'Confirm author credit for ' + code, '--', 'authors.json')
        git('push', 'origin', 'main')
        return {'ok': True, 'published': True, 'registry': data,
                'message': '作者已确定并推送；在线看板部署后自动更新。'}
    except RuntimeError:
        return {'ok': True, 'published': False, 'registry': data,
                'message': '作者已确定并保存到本机资源库，线上同步失败。请点击“确定并同步”重试。'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self):
        return (self.headers.get('Host') == '127.0.0.1:17843' and
                self.headers.get('Origin', '').lower() in ORIGINS)

    def reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        origin = self.headers.get('Origin', '')
        if origin.lower() in ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Author-Confirm')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.reply(200 if self.allowed() else 403, {})

    def do_GET(self):
        if not self.allowed() or self.path != '/authors':
            self.reply(403, {'error': '不允许的请求'})
            return
        try:
            with LOCK:
                self.reply(200, read(LIB / 'authors.json'))
        except Exception:
            self.reply(503, {'error': '本机资源库暂时不可用'})

    def do_POST(self):
        if not self.allowed() or self.path != '/confirm' or self.headers.get('X-Author-Confirm') != '1':
            self.reply(403, {'error': '不允许的请求'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('请求长度不正确')
            payload = json.loads(self.rfile.read(size))
            with LOCK:
                result = confirm(payload)
            self.reply(200, result)
        except ValueError as e:
            self.reply(409, {'error': str(e)})
        except Exception:
            self.reply(503, {'error': '保存服务暂时不可用，请重试；不要关闭尚未保存的署名。'})

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 17843), Handler).serve_forever()
