"""Local deterministic movie receiver. Run, then click Export in /?capture=1.

Frames are rendered by the app's WebGL context and encoded with NVIDIA NVENC.
Only accepts same-origin POSTs on loopback; outputs stay in project videos/.
"""
import functools
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT.parent / 'core'          # 共用模組與 three.js：頁面的 importmap 指向 ../core/


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """正確 MIME、停用快取；/core/ 對應到 TestCode/core。"""
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
                      '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8'}

    def translate_path(self, path):
        p = urlsplit(path).path
        if p.startswith('/core/'):
            target = (CORE / unquote(p[len('/core/'):])).resolve()
            return str(target) if str(target).startswith(str(CORE.resolve())) else str(CORE / '__denied__')
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


class ReusableTCPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

PORT = 8766
OUTPUT = ROOT / 'videos'
FFMPEG = ROOT / 'tools' / 'bin' / 'ffmpeg.exe'
LOCK = threading.Lock()
JOB = None


class Handler(QuietHandler):
    def answer(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global JOB
        if self.headers.get('Origin') != f'http://127.0.0.1:{PORT}':
            return self.answer(403, {'error': 'Same-origin requests only'})
        length = int(self.headers.get('Content-Length', 0))
        if not 0 <= length <= 12_000_000:
            return self.answer(413, {'error': 'Request too large'})
        body = self.rfile.read(length)
        with LOCK:
            try:
                if self.path == '/render/start':
                    spec = json.loads(body)
                    if JOB and JOB['process'].poll() is None:
                        if JOB['spec'] == spec:
                            return self.answer(200, {'token': JOB['token'], 'nextFrame': JOB['frames']})
                        raise ValueError('An export is already running')
                    if (spec['width'], spec['height'], spec['fps']) != (1920, 1080, 30) or not 1 <= spec['frames'] <= 30000:
                        raise ValueError('Invalid video specification')
                    OUTPUT.mkdir(exist_ok=True)
                    name = 'V110_QC_1080p30'
                    file = OUTPUT / (name + '.mp4')
                    suffix = 2
                    while file.exists():
                        file = OUTPUT / f'{name}_{suffix}.mp4'
                        suffix += 1
                    log = file.with_suffix('.encode.log').open('wb')
                    cmd = [str(FFMPEG), '-hide_banner', '-n', '-f', 'image2pipe', '-framerate', '30', '-vcodec', 'mjpeg', '-i', 'pipe:0', '-an', '-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(file)]
                    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                    JOB = {'process': process, 'file': file, 'frames': 0, 'spec': spec, 'token': secrets.token_urlsafe(24), 'log': log}
                    file.with_suffix('.shots.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(f'START {spec["frames"]} frames; GPU {spec["gpu"]}', flush=True)
                    return self.answer(200, {'token': JOB['token']})
                if not JOB or not secrets.compare_digest(self.headers.get('X-Render-Token', ''), JOB['token']):
                    return self.answer(403, {'error': 'Invalid render token'})
                if self.path == '/render/frame':
                    index = int(self.headers.get('X-Frame-Index', -1))
                    digest = hashlib.sha256(body).hexdigest()
                    if index == JOB['frames'] - 1 and digest == JOB.get('last_hash'):
                        return self.answer(200, {'frame': index})
                    if index != JOB['frames'] or index >= JOB['spec']['frames'] or body[:2] != b'\xff\xd8':
                        raise ValueError('Missing, unordered or invalid frame')
                    JOB['process'].stdin.write(body)
                    JOB['process'].stdin.flush()
                    JOB['frames'] += 1
                    JOB['last_hash'] = digest
                    if index % 300 == 0:
                        print(f'FRAME {index}/{JOB["spec"]["frames"]}', flush=True)
                    return self.answer(200, {'frame': index})
                if self.path == '/render/finish':
                    if JOB['frames'] != JOB['spec']['frames']:
                        raise ValueError('Incomplete movie')
                    JOB['process'].stdin.close()
                    code = JOB['process'].wait(timeout=60)
                    JOB['log'].close()
                    if code:
                        raise RuntimeError('FFmpeg failed; see encode log')
                    print(f'COMPLETE {JOB["file"]}', flush=True)
                    return self.answer(200, {'file': str(JOB['file'])})
                self.answer(404, {'error': 'Unknown endpoint'})
            except Exception as error:
                self.answer(400, {'error': str(error)})


if __name__ == '__main__':
    if not FFMPEG.exists():
        raise SystemExit(f'Install an NVENC-enabled ffmpeg at {FFMPEG}')
    handler = functools.partial(Handler, directory=str(ROOT / 'web'))
    with ReusableTCPServer(('127.0.0.1', PORT), handler) as server:
        print(f'Movie export: http://127.0.0.1:{PORT}/?capture=1', flush=True)
        server.serve_forever()
