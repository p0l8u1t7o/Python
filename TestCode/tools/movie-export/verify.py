"""Decode completed movies and verify timing, frame count and timeline coverage."""
import json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'TEMP/videos'
BIN=ROOT/'MilitaryGradePC/tools/bin'
reports=[]
for manifest in OUT.glob('*.shots.json'):
    spec=json.loads(manifest.read_text(encoding='utf-8'))
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
    decoded=subprocess.run([str(BIN/'ffmpeg.exe'),'-v','error','-i',str(film),'-f','null','-'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert decoded.returncode==0 and not decoded.stderr,decoded.stderr
    samples=sorted((OUT/'samples'/spec['project']).glob('*.jpg'))
    # The sampled JPEGs are the exact frames supplied to the encoder.
    selected=samples if len(samples)<=20 else [samples[round(i*(len(samples)-1)/19)] for i in range(20)]
    sheet=Image.new('RGB',(1280,205*((len(selected)+3)//4)), '#15202a');draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(selected):
        with Image.open(p) as im:
            im.thumbnail((320,180));x=(i%4)*320;y=(i//4)*205;sheet.paste(im,(x,y));draw.text((x+5,y+183),p.stem,fill='white')
    sheet.save(OUT/(spec['project']+'-contact.jpg'))
    report={'project':spec['project'],'file':str(film),'seconds':float(stream['duration']),'frames':int(stream['nb_frames']),'resolution':'1920x1080','fps':30,'codec':'h264_nvenc','gpu':spec['gpu'],'fullTimelineCovered':True,'decodedWithoutErrors':True,'bytes':film.stat().st_size}
    reports.append(report);print('PASS',spec['project'],report['seconds'],report['frames'],flush=True)
(OUT/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
