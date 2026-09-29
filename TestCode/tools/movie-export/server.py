"""Loopback-only deterministic JPEG receiver; MP4 and samples stay in TEMP."""
import argparse, functools, hashlib, http.server, json, re, secrets, socket, subprocess, threading
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'TEMP' / 'videos'
SITE = ROOT / 'TEMP' / 'movie-site'
FFMPEG = ROOT / 'MilitaryGradePC' / 'tools' / 'bin' / 'ffmpeg.exe'
PORT = 8782
ENCODER = 'h264_nvenc'
JOBS = {}
LOCK = threading.Lock()
PROJECTS = ['RobotArmPressSSD', 'shutter assembly', 'PCB-CopperAssembly', 'MilitaryGradePC', 'AutomaticAcid-BaseTitration', 'WorkpieceMeasurement']

class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    def log_message(self, *args): pass
    def answer(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/render/status':
            return self.answer(200, {name:{'frames':j['frames'],'total':j['spec']['frames'],'complete':j['complete']} for name,j in JOBS.items()})
        return super().do_GET()
    def do_POST(self):
        if self.headers.get('Origin') != f'http://127.0.0.1:{PORT}': return self.answer(403, {'error':'Same origin only'})
        length=int(self.headers.get('Content-Length',0))
        if not 0<=length<=12000000:return self.answer(413, {'error':'Payload too large'})
        body=self.rfile.read(length)
        with LOCK:
            try:
                if self.path=='/render/audit-start':
                    spec=json.loads(body);name=spec['project']
                    if name not in PROJECTS:raise ValueError('Invalid project')
                    audit=OUT/'audit'/name;audit.mkdir(parents=True,exist_ok=True)
                    (audit/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
                    return self.answer(200,{'ok':True})
                if self.path=='/render/audit-frame':
                    name=unquote(self.headers.get('X-Project',''));sample_name=self.headers.get('X-Sample-Name','')
                    if name not in PROJECTS or not re.fullmatch(r'(frame-\d{6}|repeat-\d{2})',sample_name) or not body.startswith(b'\xff\xd8'):raise ValueError('Invalid audit sample')
                    audit=OUT/'audit'/name;audit.mkdir(parents=True,exist_ok=True)
                    (audit/(sample_name+'.jpg')).write_bytes(body)
                    (audit/(sample_name+'.json')).write_text(json.dumps(json.loads(self.headers['X-Telemetry']),indent=2),encoding='utf-8')
                    return self.answer(200,{'ok':True})
                if self.path=='/render/start':
                    spec=json.loads(body);name=spec['project']
                    if name not in PROJECTS or (spec['width'],spec['height'],spec['fps'])!=(1920,1080,30) or not 1<=spec['frames']<=150000:raise ValueError('Invalid specification')
                    if name in JOBS:
                        j=JOBS[name]
                        if j['spec']!=spec:raise ValueError('Changed specification; restart receiver')
                        return self.answer(200,{'token':j['token'],'nextFrame':j['frames'],'complete':j['complete']})
                    OUT.mkdir(parents=True,exist_ok=True)
                    file=OUT/(name+'_1080p30.mp4')
                    if file.exists():raise ValueError('Output already exists: '+str(file))
                    log=file.with_suffix('.encode.log').open('wb')
                    encoding=['-c:v','h264_nvenc','-preset','p6','-tune','hq','-rc','vbr','-cq','18','-b:v','0'] if ENCODER=='h264_nvenc' else ['-c:v','libx264','-preset','medium','-crf','18']
                    cmd=[str(FFMPEG),'-hide_banner','-n','-f','image2pipe','-framerate','30','-vcodec','mjpeg','-i','pipe:0','-an',*encoding,'-pix_fmt','yuv420p','-movflags','+faststart',str(file)]
                    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                    samples={0,spec['frames']-1}
                    for s in spec['shots']:
                        if s['kind']!='process' or s.get('firstInPhase'):samples.add(min(spec['frames']-1,s['startFrame']+int(s['frameCount']*.6)))
                    samples.update(round(i*(spec['frames']-1)/24) for i in range(25))
                    JOBS[name]={'spec':spec,'token':secrets.token_urlsafe(24),'process':proc,'file':file,'log':log,'frames':0,'complete':False,'samples':samples}
                    file.with_suffix('.shots.json').write_text(json.dumps(dict(spec,encoder=ENCODER),ensure_ascii=False,indent=2),encoding='utf-8')
                    print('START',name,spec['frames'],flush=True)
                    return self.answer(200,{'token':JOBS[name]['token'],'nextFrame':0})
                j=next((j for j in JOBS.values() if secrets.compare_digest(self.headers.get('X-Render-Token',''),j['token'])),None)
                if j is None:return self.answer(403,{'error':'Invalid token'})
                if self.path=='/render/frame':
                    i=int(self.headers.get('X-Frame-Index',-1));digest=hashlib.sha256(body).hexdigest()
                    if i==j['frames']-1 and digest==j.get('hash'):return self.answer(200,{'frame':i})
                    if i!=j['frames'] or i>=j['spec']['frames'] or not body.startswith(b'\xff\xd8'):raise ValueError('Out of order frame')
                    j['process'].stdin.write(body);j['process'].stdin.flush();j['frames']+=1;j['hash']=digest
                    if i in j['samples']:
                        d=OUT/'samples'/j['spec']['project'];d.mkdir(parents=True,exist_ok=True);(d/f'{i:06d}.jpg').write_bytes(body)
                    if i%900==0:print('FRAME',j['spec']['project'],i,j['spec']['frames'],flush=True)
                    return self.answer(200,{'frame':i})
                if self.path=='/render/finish':
                    if j['complete']:return self.answer(200,{'file':str(j['file'])})
                    if j['frames']!=j['spec']['frames']:raise ValueError('Incomplete film')
                    j['process'].stdin.close();code=j['process'].wait(timeout=60);j['log'].close()
                    if code:raise ValueError('Encoding failed')
                    j['complete']=True; print('COMPLETE',j['spec']['project'],flush=True)
                    return self.answer(200,{'file':str(j['file'])})
                return self.answer(404,{'error':'Unknown endpoint'})
            except Exception as e:return self.answer(400,{'error':str(e)})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8782);parser.add_argument('--output-subdir',default='');args=parser.parse_args();PORT=args.port
    if args.output_subdir:
        if Path(args.output_subdir).name!=args.output_subdir or args.output_subdir in ('.','..'):raise ValueError('Invalid output subdirectory')
        OUT=OUT/args.output_subdir
    probe=subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','color=size=1920x1080:rate=30','-frames:v','3','-c:v','h264_nvenc','-f','null','-'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
    if probe.returncode:ENCODER='libx264'
    print('Encoder:',ENCODER,flush=True)
    print(f'Movie server http://127.0.0.1:{PORT}',flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1',PORT),functools.partial(Handler,directory=str(SITE))).serve_forever()
