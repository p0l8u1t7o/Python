"""Decode completed movies and verify timing, frame count and timeline coverage."""
import argparse, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default='TEMP/videos')
parser.add_argument('--project')
args=parser.parse_args()
OUT=ROOT/args.output
BIN=ROOT/'MilitaryGradePC/tools/bin'
def temporal_audit(film):
    """Detect one-frame global flashes/black frames; retain metrics for review.

    This is not an optical guarantee: moving specular edges and intended
    exposure LEDs still require viewing the full-size samples.
    """
    proc=subprocess.Popen([str(BIN/'ffmpeg.exe'),'-v','error','-i',str(film),'-vf','scale=320:180','-pix_fmt','gray','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    a=b=None;count=0;black=[];worst=[]
    while True:
        data=proc.stdout.read(320*180)
        if not data:break
        assert len(data)==320*180,'Incomplete decoded frame'
        c=np.frombuffer(data,dtype=np.uint8).reshape(180,320)[27:].astype(np.int16)
        if (c<4).mean()>.995:black.append(count)
        if a is not None:
            flash=float(((np.abs(c-b)>28)&(np.abs(b-a)>28)&(np.abs(c-a)<9)).mean())
            worst.append((flash,count-1))
        a,b=b,c;count+=1
    error=proc.stderr.read().decode('utf-8',errors='replace')
    assert proc.wait()==0 and not error,error
    return {'decodedFrames':count,'blackFrames':black,'largestIsolatedFlashFractions':sorted(worst,reverse=True)[:10]}
reports=[]
for manifest in OUT.glob('*.shots.json'):
    spec=json.loads(manifest.read_text(encoding='utf-8'))
    if args.project and args.project!=spec['project']:continue
    film=manifest.with_name(manifest.name.replace('.shots.json','.mp4'))
    probe=subprocess.run([str(BIN/'ffprobe.exe'),'-v','error','-select_streams','v:0','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_frames,duration','-of','json',str(film)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if probe.returncode:
        print('Pending:',film.name);continue
    stream=json.loads(probe.stdout)['streams'][0]
    assert (stream['codec_name'],stream['width'],stream['height'],stream['r_frame_rate'])==('h264',1920,1080,'30/1'),stream
    assert int(stream['nb_frames'])==spec['frames'],stream
    assert abs(float(stream['duration'])-spec['duration'])<.05
    timeline=[s for s in spec['shots'] if s['kind']=='process']
    assert len(timeline)==spec['steps']
    assert abs(timeline[0]['simStart'])<1e-6
    for a,b in zip(timeline,timeline[1:]):assert abs(a['simStart']+a['simDuration']-b['simStart'])<1e-5
    assert abs(timeline[-1]['simStart']+timeline[-1]['simDuration']-spec['simulationDuration'])<1e-5
    assert sum(s['frameCount'] for s in spec['shots'])==spec['frames']
    if spec.get('revision')=='2026-09-29-cinematic-v2' and spec['project']=='PCB-CopperAssembly':
        details=[s for s in spec['shots'] if s['kind']=='station']
        assert len(details)==6
        assert all(s['frameCount']/spec['fps']+1/spec['fps']>=s['simDuration'] for s in details),'PCB detail replay must not compress a full cycle into a few seconds'
    samples=sorted((OUT/'samples'/spec['project']).glob('*.jpg'))
    # The sampled JPEGs are the exact frames supplied to the encoder.
    selected=samples if len(samples)<=20 else [samples[round(i*(len(samples)-1)/19)] for i in range(20)]
    sheet=Image.new('RGB',(1280,205*((len(selected)+3)//4)), '#15202a');draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(selected):
        with Image.open(p) as im:
            im.thumbnail((320,180));x=(i%4)*320;y=(i//4)*205;sheet.paste(im,(x,y));draw.text((x+5,y+183),p.stem,fill='white')
    sheet.save(OUT/(spec['project']+'-contact.jpg'))
    temporal=temporal_audit(film)
    assert temporal['decodedFrames']==spec['frames'] and not temporal['blackFrames'],temporal
    report={'project':spec['project'],'file':str(film),'seconds':float(stream['duration']),'frames':int(stream['nb_frames']),'resolution':'1920x1080','fps':30,'codec':spec.get('encoder','not_recorded'),'gpu':spec['gpu'],'revision':spec.get('revision','legacy'),'supersampling':spec.get('supersampling',1),'fullTimelineCovered':True,'decodedWithoutErrors':True,'temporalAudit':temporal,'bytes':film.stat().st_size}
    reports.append(report);print('PASS',spec['project'],report['seconds'],report['frames'],flush=True)
expected={args.project} if args.project else {'AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly'}
assert {r['project'] for r in reports}==expected,'Some required movies are incomplete'
(OUT/('verification.json' if not args.project else args.project+'-verification.json')).write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
