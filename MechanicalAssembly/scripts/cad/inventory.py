"""Read-only source inventory; regenerate with npm run inventory."""
from pathlib import Path
import os, json, collections, re
BASE = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('CAD_SOURCE_DIR') or BASE.parent / 'TestCode' / 'Temp' / '自動爆炸圖與拆圖CAD設計')
files = sorted(p for p in SOURCE.rglob('*') if p.is_file() and not p.name.startswith('~$'))
entries = [{'path': p.relative_to(SOURCE).as_posix(), 'name': p.name, 'bytes': p.stat().st_size, 'format': p.suffix.lower()[1:]} for p in files]
stations = []
for folder in sorted(SOURCE.iterdir()):
    if folder.is_dir() and re.match(r'202401-[A-J]A00', folder.name):
        related = [e for e in entries if e['path'].startswith(folder.name + '/')]
        code = folder.name[:11]
        stations.append({'id': code, 'name': folder.name[11:].strip(' _'), 'folder': folder.name, 'files': related, 'formats': dict(collections.Counter(e['format'] for e in related))})
pdfs = []
try:
    import pymupdf as fitz
    for p in files:
        if p.suffix.lower() == '.pdf':
            doc = fitz.open(p)
            pdfs.append({'name': p.name, 'path': p.relative_to(SOURCE).as_posix(), 'pages': len(doc), 'text': '\n'.join(page.get_text() for page in doc)[:16000]})
    doc = fitz.open(SOURCE / 'Wet Processing Machine_部件圖.PDF')
    (BASE / 'tmp').mkdir(exist_ok=True)
    doc[0].get_pixmap(matrix=fitz.Matrix(1, 1)).save(BASE / 'tmp' / 'source-drawing.png')
except ImportError:
    print('PDF library missing; file inventory remains available.')
result = {'schemaVersion': 1, 'name': 'SAT 晶片濕製程自動線', 'source': str(SOURCE), 'counts': dict(collections.Counter(e['format'] for e in entries)), 'stations': stations, 'files': entries, 'drawings': pdfs}
(BASE / 'public' / 'data').mkdir(parents=True, exist_ok=True)
(BASE / 'public' / 'data' / 'source-inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'{len(files)} files, {len(stations)} stations, {len(pdfs)} PDFs read')
for pdf in pdfs:
    if '/' not in pdf['path']:
        print(pdf['name'], pdf['pages'], pdf['text'][:500].replace('\n', ' '))
