"""Check generated circuit books and optionally render every PDF page for review.

Usage: python tools/circuit-drawings/verify.py [--render]
Set PDFTOPPM to override the Windows bundled renderer path.
"""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pypdf import PdfReader
from render import ROOT, W, H, width

NS={'s':'http://www.w3.org/2000/svg'}
POPPLER=os.environ.get('PDFTOPPM',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'))
OUT=ROOT/'TEMP/circuit-review/P02'


def check(datafile):
    d=json.loads(datafile.read_text(encoding='utf-8'));folder=datafile.parent
    pdf=folder.parent/'circuit-diagrams.pdf';pages=PdfReader(pdf).pages
    errors=[];overlaps=[];texts=[]
    svgfiles=sorted(folder.glob('E[0-9][0-9].svg'))
    if len(pages)!=len(svgfiles):errors.append('PDF/SVG page counts differ')
    for i,(page,svg) in enumerate(zip(pages,svgfiles)):
        if abs(float(page.mediabox.width)-W)>.1 or abs(float(page.mediabox.height)-H)>.1:errors.append('Not A3 landscape')
        text=page.extract_text();texts.append(text)
        if 'P02' not in text or 'TESTCODE' not in text:errors.append('Missing title block')
        root=ET.parse(svg).getroot();items=[]
        for group,sy,dy in [(root,1,0),(root.find('s:g',NS),.94,-39)]:
            for t in group.findall('s:text',NS):
                value=t.text or '';x=float(t.attrib['x']);size=float(t.attrib['font-size']);y=float(t.attrib['y'])*sy+dy
                bounds=(x,y-size*sy,x+width(value,size),y)
                if group is not root and bounds[3]>706:errors.append(f'{svg.name}: content touches footer: {value}')
                items.append((value,bounds))
        for a,(value,bounds) in enumerate(items):
            for other,b in items[a+1:]:
                dx=min(bounds[2],b[2])-max(bounds[0],b[0]);dy=min(bounds[3],b[3])-max(bounds[1],b[1])
                if dx>1 and dy>2:overlaps.append({'page':svg.name,'a':value,'b':other})
    full='\n'.join(texts)
    for p in d['components']:
        if p['id'] not in full or p['title'] not in full:errors.append('Missing component '+p['id'])
    for p in d['axes']:
        if 'W-M-'+p['id'] not in full or 'W-E-'+p['id'] not in full:errors.append('Missing axis wiring '+p['id'])
    for r in d['io']:
        if r['wire'] not in full or r['terminal'] not in full or r['function'] not in full:errors.append('Missing IO '+r['signal'])
        count=sum(r['wire'] in t for t in texts)
        if count<2:errors.append('IO missing drawing or schedule '+r['signal'])
    if len(d['io'])!=len({r['signal'] for r in d['io']}):errors.append('Duplicate IO signal')
    result=dict(project=d['project'],revision=d['revision'],pdf_pages=len(pages),svg_pages=len(svgfiles),components=len(d['components']),axes=len(d['axes']),io_points=len(d['io']),pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),errors=errors,text_overlap_candidates=overlaps)
    (folder/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return d,pdf,result


def render(item):
    from PIL import Image,ImageDraw
    d,pdf,_=item;dest=OUT/d['code'];dest.mkdir(parents=True,exist_ok=True)
    subprocess.run([POPPLER,'-r','85','-png',str(pdf),str(dest/'page')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    pages=sorted(dest.glob('page-*.png'))
    for start in range(0,len(pages),6):
        sheet=Image.new('RGB',(1500,1660),'#d7d7d7');draw=ImageDraw.Draw(sheet)
        for n,f in enumerate(pages[start:start+6]):
            im=Image.open(f);im.thumbnail((738,512));x=6+(n%2)*750;y=25+(n//2)*550
            sheet.paste(im,(x,y));draw.text((x,y-17),d['code']+' / '+f.stem,fill='black')
        sheet.save(OUT/(d['code']+'-contact-'+str(start//6+1)+'.png'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--render',action='store_true');args=parser.parse_args()
    results=[check(p) for p in sorted(ROOT.glob('*/docs/electrical/circuit-data.json'))]
    if args.render:
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(render,results))
    for _,_,r in results:print(json.dumps(r,ensure_ascii=True))
    if any(r['errors'] or r['text_overlap_candidates'] for _,_,r in results):raise SystemExit('Review checks failed')


if __name__=='__main__':main()
