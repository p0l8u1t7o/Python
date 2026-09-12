"""Verify the delivered movie and render a review contact sheet from the MP4."""
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageStat, ImageChops

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'tools' / 'bin'
VIDEO = ROOT / 'videos' / 'V110_QC_1080p30.mp4'
SPEC = json.loads(VIDEO.with_suffix('.shots.json').read_text(encoding='utf-8'))
REVIEW = ROOT / 'review' / 'video'
REVIEW.mkdir(exist_ok=True)


def run(program, args):
    return subprocess.run([str(BIN / program), *args], check=True, capture_output=True)


probe = json.loads(run('ffprobe.exe', ['-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(VIDEO)]).stdout)
stream = probe['streams'][0]
assert (stream['codec_name'], stream['width'], stream['height'], stream['avg_frame_rate']) == ('h264', 1920, 1080, '30/1')
assert int(stream['nb_read_frames']) == SPEC['frames'] == 5580
assert abs(float(probe['format']['duration']) - SPEC['frames'] / 30) < .001
decoded = run('ffmpeg.exe', ['-v', 'error', '-i', str(VIDEO), '-f', 'null', '-'])
assert not decoded.stderr, decoded.stderr.decode(errors='replace')


def time_of(label, portion=.5):
    shot = next(s for s in SPEC['shots'] if s['label'] == label)
    return shot['videoStart'] + shot['duration'] * portion


def extract(seconds, path):
    run('ffmpeg.exe', ['-v', 'error', '-y', '-ss', str(seconds), '-i', str(VIDEO), '-frames:v', '1', '-q:v', '2', str(path)])
    return Image.open(path).convert('RGB')


moments = [
    ('Overview', 1),
    ('Infeed', time_of('推出最底層載具')),
    ('Cover opening', time_of('D1 沿鉸鏈弧線開門')),
    ('Connector capture', time_of('D1 連接器取像')),
    ('180 degree flip', time_of('翻面 180°')),
    ('Docking inspection', time_of('取像：外露 Docking 接點')),
    ('Outfeed', time_of('載具拉入出料堆料架')),
    ('Stack lift', time_of('出料平台上升一個間距')),
    ('Complete', SPEC['duration']-1),
]
sheet = Image.new('RGB', (1440, 882), '#101923')
draw = ImageDraw.Draw(sheet)
for i, (label, seconds) in enumerate(moments):
    img = extract(seconds, REVIEW / f'{i+1:02d}.jpg')
    assert sum(ImageStat.Stat(img.crop((0, 170, 1920, 870))).mean) > 20, label
    img.thumbnail((480, 270))
    x, y = i % 3 * 480, i // 3 * 294
    sheet.paste(img, (x, y))
    draw.text((x+10, y+276), f'{seconds:06.2f}s  {label}', fill='#a5d8df')
sheet.save(REVIEW / 'contact-sheet.jpg', quality=94)

motions = {}
for label in ['推出最底層載具', 'D1 沿鉸鏈弧線開門', '翻面 180°', '載具拉入出料堆料架', '出料平台上升一個間距']:
    first = extract(time_of(label, .2), REVIEW / 'motion-start.jpg').crop((0, 170, 1920, 870))
    last = extract(time_of(label, .8), REVIEW / 'motion-end.jpg').crop((0, 170, 1920, 870))
    difference = sum(ImageStat.Stat(ImageChops.difference(first, last)).mean) / 3
    assert difference > .1, f'Frozen scene: {label}'
    motions[label] = difference

report = {'file': str(VIDEO), 'codec': stream['codec_name'], 'width': 1920, 'height': 1080, 'fps': '30/1', 'frames': int(stream['nb_read_frames']), 'duration': float(probe['format']['duration']), 'bytes': int(probe['format']['size']), 'decodeErrors': 0, 'gpu': SPEC['gpu'], 'motionPixelDifferences': motions}
(REVIEW / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
