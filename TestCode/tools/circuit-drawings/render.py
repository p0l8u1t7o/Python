"""Render each project's electrical/circuit-data.json to A3 PDF and editable SVG.

Usage: python tools/circuit-drawings/render.py [project-folder ...]
Requires reportlab; Chinese font is embedded in the PDF. No simulation is changed.
"""
from pathlib import Path
import argparse
import html
import json
import math
import os
import re
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from cad_sheets import panel_layout, point_wiring, drive_wiring, workstation_layout, cad_power

ROOT = Path(__file__).resolve().parents[2]
W, H = 1190.55, 841.89  # A3 landscape, points
FONT_PATH = os.environ.get('CIRCUIT_FONT', 'C:/Windows/Fonts/msjh.ttc')
pdfmetrics.registerFont(TTFont('CJK', FONT_PATH, subfontIndex=0))
INK, MUTED, GRID = '#111111', '#333333', '#555555'
AC, DC, PE, NET, SAFE, SIGNAL = '#cb00c9', '#0039e6', '#00a529', '#111111', '#111111', '#111111'
WIRE, DIM = '#006633', '#00a9b9'
QA = []


def width(s, size=12):
    return pdfmetrics.stringWidth(str(s), 'CJK', size)


def wrap(s, limit, size=12):
    lines, line = [], ''
    for ch in str(s):
        if ch == '\n' or (line and width(line + ch, size) > limit):
            lines.append(line)
            line = '' if ch == '\n' else ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


class Drawing:
    def __init__(self, data):
        self.d = data
        self.docs = ROOT / data['project'] / 'docs'
        self.out = self.docs / 'electrical'
        self.pdf = canvas.Canvas(str(self.docs / 'circuit-diagrams.pdf'), pagesize=(W, H), pageCompression=1)
        self.pdf.setTitle(data['title'] + ' - 電路圖 ' + data['revision'])
        self.pdf.setAuthor('TestCode - Electrical Planning')
        self.pages, self.svg, self.errors = [], None, []

    def line(self, x1, y1, x2, y2, color=INK, dash=False, thick=0.55):
        self.pdf.setStrokeColor(color); self.pdf.setLineWidth(thick)
        self.pdf.setDash([5, 3] if dash else [])
        self.pdf.line(x1, H-y1, x2, H-y2)
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{thick}"'+(' stroke-dasharray="5 3"' if dash else '')+'/>')
        self.pdf.setDash([])

    def rect(self, x, y, w, h, fill='white', stroke=INK):
        self.pdf.setFillColor(fill); self.pdf.setStrokeColor(stroke); self.pdf.setLineWidth(0.5)
        self.pdf.rect(x, H-y-h, w, h, fill=1, stroke=1)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>')

    def circle(self, x, y, r=2.5, color=INK, fill=True):
        self.pdf.setStrokeColor(color); self.pdf.setFillColor(color if fill else 'white')
        self.pdf.circle(x, H-y, r, fill=1, stroke=1)
        self.svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color if fill else "white"}" stroke="{color}"/>')

    def text(self, x, y, value, size=12, color=INK, limit=None):
        lines = wrap(value, limit, size) if limit else str(value).split('\n')
        for i, s in enumerate(lines):
            yy = y+i*size*1.45
            if x < 15 or x+width(s, size) > W-15 or yy < 6 or yy+size > H-6:
                self.errors.append(dict(page=self.id, text=s, x=x, y=yy))
            self.pdf.setFillColor(color); self.pdf.setFont('CJK', size)
            self.pdf.drawString(x, H-yy-size, s)
            self.svg.append(f'<text x="{x}" y="{yy+size}" font-family="Microsoft JhengHei,Noto Sans TC,sans-serif" font-size="{size}" fill="{color}">{html.escape(s)}</text>')
        return len(lines)*size*1.45

    def box(self, x, y, w, h, title, sub='', color=INK):
        self.rect(x,y,w,h,'white',INK)
        used=self.text(x+10,y+8,title,13,color,limit=w-20)
        if sub:
            used+=self.text(x+10,y+12+used,sub,10.5,MUTED,limit=w-20)+4
        if used > h-10:
            self.errors.append(dict(page=self.id,overflow=title,height=h,used=used))

    def arrow(self,x1,y,x2,label='',color=NET):
        self.line(x1,y,x2,y,color)
        self.line(x2-6,y-3,x2,y,color); self.line(x2-6,y+3,x2,y,color)
        if label:self.text(x1+12,y-21,label,11,color,limit=x2-x1-20)

    def earth(self,x,y):
        self.line(x,y,x,y+12,PE)
        for i,w in enumerate([20,13,6]):self.line(x-w/2,y+12+i*4,x+w/2,y+12+i*4,PE)

    def contact(self,x,y,label,nc=True,color=SAFE):
        self.line(x-20,y,x-7,y,color);self.line(x+7,y,x+20,y,color)
        self.line(x-7,y-9,x-7,y+9,color);self.line(x+7,y-9,x+7,y+9,color)
        if nc:self.line(x-12,y+12,x+12,y-12,color)
        self.text(x-36,y-34,label,10,color)

    def new(self,title,subtitle='',code=None):
        if self.svg is not None:self.finish_page()
        self.id=f'E{len(self.pages)+1:02}'
        self.sheet=str(code or (600+len(self.pages)))
        self.title=title
        self.pdf.bookmarkPage(self.id)
        self.pdf.addOutlineEntry(self.sheet+' / '+title,self.id,level=0)
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="420mm" height="297mm"><title>{html.escape(self.d["title"]+" / "+title)}</title><rect width="100%" height="100%" fill="white"/>']
        self.rect(15,6,W-30,H-12)
        self.rect(37,30,W-74,H-60)
        for n in range(7):
            x=37+(W-74)*n/6
            self.line(x,6,x,30);self.line(x,H-30,x,H-6)
            if n<6:
                self.text(x+(W-74)/12-4,9,n+1,12)
                self.text(x+(W-74)/12-4,H-23,n+1,12)
            for k in range(1,9):
                if n<6:
                    xx=x+k*(W-74)/54
                    self.line(xx,20,xx,30,thick=.35);self.line(xx,H-30,xx,H-20,thick=.35)
        for n in range(5):
            y=30+(H-60)*n/4
            self.line(15,y,37,y);self.line(W-37,y,W-15,y)
            if n<4:
                self.text(21,y+(H-60)/8-6,'ABCD'[n],12)
                self.text(W-30,y+(H-60)/8-6,'ABCD'[n],12)
        # Reference-style title block: neutral project identity, no copied signatures.
        self.rect(40,728,W-80,82)
        for x in [262,414,534,654,1108]:self.line(x,728,x,810 if x!=414 else 769)
        self.line(262,769,W-40,769)
        self.text(60,745,'TESTCODE',28)
        self.text(61,785,'ELECTRICAL ENGINEERING',10)
        fields=[(280,733,'DATE',self.d['date'].replace('-','')),(427,733,'DRAWING BY','Codex'),(545,733,'DESIGNED BY','待確認'),(281,775,'CHECKED BY','待確認'),(545,775,'APPROVAL BY','待確認')]
        for x,y,label,value in fields:
            self.text(x,y,label,7.5);self.text(x,y+12,value,14)
        self.text(666,733,'Project',8)
        size=min(19,390/max(1,width(self.d['title'],1)))
        self.text(710,745,self.d['title'],size)
        self.text(666,777,'Type.',8)
        size=min(19,385/max(1,width(title,1)))
        self.text(710,784,title,size)
        self.text(1117,742,self.d['revision'],13)
        self.text(1116,775,'Page',8);self.text(1115,788,self.sheet,15)
        self.text(48,43,subtitle or self.d['status'],10,limit=1090)
        self.text(48,711,'工程規劃／非施工放行  |  功能端子非原廠腳位  |  * 新增或待選  |  尺寸 mm／示意無比例',8)
        # Existing content coordinates reflow into the reference drawing area.
        self.pdf.saveState();self.pdf.translate(0,H-(H*.94)+39);self.pdf.scale(1,.94)
        self.svg.append('<g transform="translate(0,-39) scale(1,.94)">')

    def finish_page(self):
        self.svg.append('</g></svg>');self.pdf.restoreState()
        name=f'{self.id}.svg';(self.out/name).write_text('\n'.join(self.svg),encoding='utf-8')
        self.pages.append(dict(id=self.id,code=self.sheet,title=self.title,file='electrical/'+name))
        self.pdf.showPage()

    def notes(self,lines,y=680):
        for s in lines:
            y+=self.text(48,y,'• '+s,11,MUTED,limit=W-100)+6
        if y>769:self.errors.append(dict(page=self.id,notes_bottom=y))

    def table(self,headers,rows,colwidths,top=128,size=11):
        x=46
        for s,w in zip(headers,colwidths):
            self.rect(x,top,w,32,'white',INK);self.text(x+8,top+8,s,size,INK);x+=w
        y=top+32
        for i,row in enumerate(rows):
            heights=[len(wrap(s,w-16,size))*size*1.45 for s,w in zip(row,colwidths)]
            rh=max(30,max(heights)+13)
            x=46
            for s,w in zip(row,colwidths):
                self.rect(x,y,w,rh,'white',GRID)
                self.text(x+8,y+6,s,size,limit=w-16);x+=w
            y+=rh
        if y>747:self.errors.append(dict(page=self.id,table_bottom=y))
        return y

    def save(self):
        self.finish_page();self.pdf.save()
        # Remove only this generator's obsolete, numbered sheets after pagination changes.
        for old in self.out.glob('E*.svg'):
            if re.fullmatch(r'E\d{2}\.svg',old.name) and int(old.stem[1:])>len(self.pages):
                if old.resolve().parent!=self.out.resolve():raise ValueError('Output escaped project folder')
                if '<title>'+html.escape(self.d['title'])+' / ' in old.read_text(encoding='utf-8'):
                    old.unlink()
        index=['# '+self.d['title']+'：電路圖','',
               '**'+self.d['status']+' / '+self.d['revision']+'**。PDF 為 A3 橫式，可縮放列印；SVG 可用瀏覽器或向量編輯器開啟。','',
               '[下載完整 PDF](circuit-diagrams.pdf) · [編輯圖面資料](electrical/circuit-data.json)','',
               '本次採參考圖冊的 A3 座標圖框、下方簽核欄、細線元件與分色配線。僅借用格式；原參考設備的公司標誌、簽名與電氣規格不沿用。','', '盤面包絡依現有 3D，面板補充空間與配線待深化；各頁功能接線不是施工放行圖。','', '## 圖紙目錄','']
        index += [f'- [{p["code"]} {p["title"]}]({p["file"]})' for p in self.pages]
        index += ['','## 設計依據與限制','']+[f'- {s}' for s in self.d.get('common_notes',[])+self.d['notes']]
        if self.d.get('added'):
            index+=['','## 相對現有 3D 新增／補齊的規劃','']+['- '+x for x in self.d['added']]
        index+=['','## 專案來源','']+[f'- [{s}](../{s})' for s in self.d['sources']]
        reference_date=self.d['date'] if self.d['code']=='WPM' else '2026-09-27'
        index+=['',f'## 核對來源（{reference_date}）','']+[f'- [{title}]({url})' for title,url in self.d['references']]
        if self.d['references']:index+=['','原廠來源用於核對控制器安全介面型式；本圖沒有擅填原廠端子腳位或宣稱安全等級。']
        index+=['','## 編修與重建','',f'在 TestCode 根目錄執行 `python tools/circuit-drawings/render.py "{self.d["project"]}"`。圖紙、清單與 PDF 使用同一份專案內 JSON 資料。','']
        (self.docs/'circuit-diagrams.md').write_text('\n'.join(index),encoding='utf-8')
        QA.append(dict(project=self.d['project'],pages=self.pages,layout_errors=self.errors))


def safety(g):
    d=g.d;g.new('安全回路功能接線','雙通道分開接收；圖中 T / SI / SO 為功能名稱，不是 GC1 實際端子編號。',code='105')
    g.box(432,125,208,490,'GC1 安全控制器','測試脈衝、輸入型式、\n安全邏輯與輸出分配待定',SAFE)
    for y,ch in [(222,'CH1'),(274,'CH2')]:
        g.text(52,y-20,'GC1 T-'+ch,11,SAFE);g.line(170,y,222,y,SAFE)
        g.contact(242,y,'S0 急停 '+ch);g.line(262,y,432,y,SAFE);g.text(330,y-20,'SI-EST-'+ch,10,SAFE)
    g.box(52,324,225,92,d['guards'],'各防護裝置独立成對輸入；\n如為接點式則使用對應測試輸出',SAFE)
    for y,ch in [(350,'CH1'),(388,'CH2')]:
        g.line(277,y,432,y,SAFE);g.text(300,y-20,'SI-GUARD-'+ch,9.5,SAFE)
    g.text(52,465,'受保護 +24 V',11,DC);g.line(172,480,222,480,DC)
    g.contact(242,480,'S1 手動復歸',False);g.line(262,480,432,480,SAFE);g.text(347,458,'RESET',10,SAFE)
    g.text(52,550,'GC1 EDM 測試',11,SAFE);g.line(170,564,190,564,SAFE)
    g.contact(210,564,'K1 回授 NC');g.line(230,564,284,564,SAFE)
    g.contact(304,564,'K2* 回授 NC');g.line(324,564,432,564,SAFE);g.text(366,541,'EDM',10,SAFE)
    target='各驅動安全停止介面*' if d['code']=='PCB' else 'RC1 原廠安全介面'
    g.box(850,174,280,100,target,'經相容安全介面／安全繼電器*；\n急停、保護停止與自動允許分開核對',SAFE)
    for y,ch in [(204,'A'),(248,'B')]:g.arrow(640,y,850,'安全路徑 '+ch,SAFE)
    for y,label in [(354,'K1'),(444,'K2*')]:
        g.arrow(640,y,860,'SO-'+label+'／介面*',SAFE)
        g.circle(890,y,22,color=SAFE,fill=False);g.text(880,y-9,label,10,SAFE)
        g.line(912,y,955,y,DC);g.line(955,y,955,y+24,DC);g.text(969,y+12,'A2 → 0 V',10,DC)
        g.text(820,y+28,'線圈額定／抑制與測試相容性待定',10,MUTED)
    g.box(850,532,280,76,'VSAFE* 氣動安全功能','安全排氣／保持壓力／防墜方案待定',SAFE)
    g.arrow(640,555,850,'獨立安全輸出*',SAFE)
    g.notes(['斷線、急停或防護開啟 → 撤銷危險動作允許；復歸只解除鎖定，不直接啟動循環。',
             'K1/K2 的冗餘數量、受控停止／能量隔離順序與 EDM 設計須經風險評估；本圖未宣稱 PL/SIL。',
             '氣動夾持／垂直軸不可假設斷電排氣就安全；防墜、保持與安全放料需另定。'],640)


def interfaces(g):
    links=g.d['links']
    for start in range(0,len(links),10):
        g.new('控制與現場介面'+('（續）' if start else ''),'箭頭表示功能資料方向；雙向交握以說明為準，通訊線與電源線不得混接。',code=102+start//10)
        for i,(a,b,label) in enumerate(links[start:start+10]):
            y=126+i*56
            g.box(52,y,310,50,a,'',NET)
            g.arrow(362,y+30,805,'',NET);g.text(377,y+3,label,10.5,NET,limit=413)
            g.box(805,y,328,50,b,'',NET)
        g.notes([g.d['notes'][0],g.d['notes'][-1]],704)


def typical_io(g):
    g.new('24 V 現場 I/O 典型接線','以下以 PNP 型式為規劃假設；原廠接口、極性及額定未定前不直接施工。',code='199')
    g.text(52,126,'A / 三線感測器 → 普通數位輸入',16,SIGNAL)
    g.box(290,175,205,138,'Bxx PNP 感測器','+24 V / 0 V / OUT',SIGNAL)
    for y,label in [(201,'X24:* +24 V'),(245,'X0:* 0 V')]:
        g.text(60,y-20,label,12,DC);g.line(215,y,290,y,DC)
    g.line(495,279,835,279,SIGNAL);g.text(535,252,'OUT → XDI:n → W-DInn',12,SIGNAL)
    g.box(835,214,284,100,'IO1 DI[n] / COM','DI[n] 接訊號；COM 接 0 V\n確定為相容 PNP 輸入模組',SIGNAL)
    g.line(760,321,990,321,DC);g.line(990,314,990,321,DC);g.text(640,307,'X0:* → COM',11,DC)
    g.text(52,365,'B / 普通數位輸出 → 電磁閥／指示負載',16,SIGNAL)
    g.box(60,423,210,94,'IO1 PNP 輸出模組','L+：受保護 +24 V\nM：0 V；負載額定待核對',SIGNAL)
    g.line(270,469,675,469,SIGNAL);g.text(300,440,'DO[n] → XDO:n → W-DOnn',12,SIGNAL)
    g.circle(711,469,36,color=SIGNAL,fill=False);g.text(691,459,'YVnn',12,SIGNAL)
    g.line(747,469,1050,469,DC);g.line(1050,469,1050,570,DC)
    g.line(270,570,1050,570,DC);g.text(60,554,'X0:* 共用回路',12,DC)
    g.line(654,469,654,544,SIGNAL);g.line(654,544,790,544,SIGNAL)
    g.box(690,529,64,30,'抑制*','',SIGNAL);g.line(790,544,790,469,DC)
    g.circle(654,469,color=SIGNAL);g.circle(790,469,color=DC)
    g.text(620,600,'* 原廠抑制模組／TVS，依線圈極性與釋放時間選定。',11,MUTED)
    g.notes(['每個現場元件另帶 +24 V 與 0 V 端子；XDI/XDO 清單列訊號端，不把多線束當作單根線。',
             'SMEMA、Remote、馬達運轉請求、相機觸發與安全回路不直接套用這兩個一般 I/O 範例。',
             '馬達經專用驅動器；荷重元／F/T 經原廠放大與資料介面，禁止接到一般數位輸入。'],648)


def schedules(g):
    for start in range(0,len(g.d['io']),18):
        g.new('I/O、端子與線號清單'+(f' / {start//18+1}'),'點序為工程分配草案，模組數、實際地址及 X 端子型式待 PLC／I/O 選型後核定。',code=500+start//18)
        rows=[[r['signal'],r['terminal'],r['wire'],r['function'],r['circuit']] for r in g.d['io'][start:start+18]]
        g.table(['功能點','規劃端子','線號','現場功能','接線型式／備註'],rows,[80,110,120,325,462],size=11)
        g.notes(['安全急停／門鎖／掃描器不占普通 DI/DO 清單；接 GC1 專用安全通道。'],727)
    axes=g.d['axes']
    for start in range(0,len(axes),14):
        g.new('驅動與馬達線束清單'+(f' / {start//14+1}'),'軸代號沿用 3D；實際功率、原廠接頭、抱閘與安全停止功能依最終驅動規格定案。',code=450+start//14)
        rows=[]
        for a in axes[start:start+14]:
            ident=a['id'];voice=bool(re.fullmatch(r'[AB]Z[1-4]',ident))
            rows.append([ident,a['title'],f'QF-{ident}* → {ident}',f'{ident} → M-{ident}',('音圈／伺服待選；專用回授' if voice else '原廠馬達＋回授分束；PE 接地')])
        g.table(['驅動','用途','電源分支*','動力線束','回授／備註'],rows,[80,260,190,185,382],size=11)
        g.notes(['各驅動需原廠編碼器／光學尺回授；機構原點／極限通道及上下料防墜另依軸規格增配。'],729)


def register(g):
    parts=g.d['components']
    for start in range(0,len(parts),14):
        g.new('元件對照表'+f' / {start//14+1}','此表來自各專案 docs/electrical-plan.md；數量為展示規劃元件，不是完整採購 BOM。',code=600+start//14)
        rows=[[p['id'],p['title'],p['model']] for p in parts[start:start+14]]
        g.table(['既有代號','元件','規劃型號／狀態'],rows,[115,385,597],size=12)
    g.new('設計註記、差異與核對來源','將已存在的工程規劃與本次新增的端子／保護／介面分開列出。',code='699')
    y=123
    for s in g.d['notes']+g.d.get('added',[]):
        y+=g.text(52,y,'• '+s,13,limit=1078)+10
    y+=15;g.text(52,y,'原始資料',15);y+=27
    for s in g.d['sources']:y+=g.text(52,y,s,11,MUTED)+5
    if g.d['references']:
        y+=15;g.text(52,y,'原廠來源（2026-09-27 核對；完整連結亦見 circuit-diagrams.md）',13);y+=26
        for title,url in g.d['references']:
            y+=g.text(52,y,title,11,NET)+3
            y+=g.text(52,y,url,9,NET,limit=1060)+8
    if y>764:g.errors.append(dict(page=g.id,notes_bottom=y))


def workstation(g):
    g.new('工作站電源與 USB 相機連接','未定義機台 PLC／致動器；此圖只涵蓋現有單眼深度軟體所需的硬體連接。',code='100')
    for i,(a,b,label) in enumerate(g.d['links'][:4]):
        y=130+i*110
        g.box(55,y,285,72,a,'',AC if i<2 else NET)
        g.arrow(340,y+35,795,'',AC if i<2 else NET)
        g.text(366,y+4,label,12,limit=408)
        g.box(795,y,330,72,b,'',AC if i<2 else NET)
    g.notes(['PE 是否存在依原廠 Class I／Class II 電源設計；不拆改電腦內部供電。',
             'USB 使用原廠線材與標準接頭；相機功耗與 USB 版本待型號確認，不能直接接 24 V。'],635)
    g.new('影像資料路徑與介面','虛線為軟體資料流程，不是新增外部接線。',code='102')
    labels=['CAM1 相機','OpenCV 取像','YOLO 深度推論','Flask 串流／API','本機瀏覽器']
    for i,label in enumerate(labels):
        x=52+i*222
        g.box(x,190,193,90,label,'CPU / GPU' if i==2 else '',NET)
        if i<4:g.line(x+193,235,x+222,235,NET,dash=True)
    g.notes(g.d['notes'],350)
    g.text(52,602,'程式來源：README.md / cameras.py / depth_cam.py / ui.py',12,MUTED)
    g.text(52,632,'供電與連接型號未指定；USB 相機為本次規劃假設，也可使用電腦內建相機。',12,MUTED)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('projects',nargs='*');args=parser.parse_args()
    files=[ROOT/p/'docs/electrical/circuit-data.json' for p in args.projects] if args.projects else sorted(ROOT.glob('*/docs/electrical/circuit-data.json'))
    for f in files:
        d=json.loads(f.read_text(encoding='utf-8'));g=Drawing(d)
        if d['code']=='WPM':
            import importlib.util
            spec=importlib.util.spec_from_file_location('wpm_circuit',ROOT/'WorkpieceMeasurement/tools/circuit_sheets.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.build(g)
        elif d['code']=='DEP':workstation_layout(g);workstation(g)
        else:panel_layout(g);cad_power(g);interfaces(g);safety(g);typical_io(g);point_wiring(g);drive_wiring(g);schedules(g);register(g)
        g.save();print(d['project'],len(g.pages),'pages;',len(g.errors),'layout issues')
    qa=ROOT/'TEMP/circuit-review';qa.mkdir(parents=True,exist_ok=True)
    (qa/'layout-checks.json').write_text(json.dumps(QA,ensure_ascii=False,indent=2),encoding='utf-8')
    if any(x['layout_errors'] for x in QA):raise SystemExit('Layout issues found; review TEMP/circuit-review/layout-checks.json')


if __name__=='__main__':main()
