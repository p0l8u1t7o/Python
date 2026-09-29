"""Review camera samples and quantify fixed-time render stability (not motion)."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='TEMP/videos/revised-20260929')
args = parser.parse_args()
root = ROOT / args.output / 'audit'
reports = []
for folder in root.iterdir():
    if not folder.is_dir():
        continue
    files = sorted(folder.glob('frame-*.jpg'))
    sheet = Image.new('RGB', (1280, 205*((len(files)+3)//4)), '#15202a')
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(files):
        with Image.open(path) as im:
            im.thumbnail((320, 180))
            sheet.paste(im, ((i%4)*320, (i//4)*205))
        draw.text(((i%4)*320+4, (i//4)*205+181), path.stem, fill='white')
    sheet.save(folder/'contact.jpg')
    repeat = [np.array(Image.open(p), dtype=np.int16) for p in sorted(folder.glob('repeat-*.jpg'))]
    diffs = [np.abs(a-b) for a, b in zip(repeat, repeat[1:])]
    report = {'project': folder.name, 'repeatFrames': len(repeat),
              'maxMeanDifference255': max((float(d.mean()) for d in diffs), default=255),
              'maxFractionChangingOver16': max((float((d.max(axis=2)>16).mean()) for d in diffs), default=1)}
    report['passed'] = len(repeat)==10 and report['maxMeanDifference255'] < .05 and report['maxFractionChangingOver16'] < .001
    reports.append(report)
    print(json.dumps(report, ensure_ascii=False))
(root/'stability.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
if not all(r['passed'] for r in reports):
    raise SystemExit('Some render stability samples are incomplete or unstable')
