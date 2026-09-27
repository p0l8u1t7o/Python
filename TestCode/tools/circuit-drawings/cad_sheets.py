"""Reference-style mounting elevations and terminal-by-terminal schematics.

All terminals are functional planning names. No vendor pin numbers are inferred.
The caller supplies the PDF/SVG Drawing so both outputs share identical geometry.
"""
import math
from reportlab.pdfbase import pdfmetrics

BLACK, BLUE, GREEN, MAGENTA, CYAN = '#111111', '#0039e6', '#006633', '#cb00c9', '#00a9b9'


def dim(g,x,y,w,h,label,vertical=False):
    if vertical:
        g.line(x,y,x,y+h,CYAN)
        for yy in [y,y+h]:
            g.line(x-5,yy,x+15,yy,CYAN)
            g.line(x-3,yy+3,x+3,yy-3,CYAN)
        g.text(x-37,y+h/2-5,label,10,MAGENTA)
    else:
        g.line(x,y,x+w,y,CYAN)
        for xx in [x,x+w]:
            g.line(xx,y-5,xx,y+15,CYAN)
            g.line(xx-3,y+3,xx+3,y-3,CYAN)
        g.text(x+w/2-20,y-17,label,10,MAGENTA)


def device(g,x,y,w,h,kind,ident):
    g.rect(x,y,w,h)
    # Contours represent planning envelopes, not exact OEM drilling templates.
    if kind in ['breaker','isolator','contactor']:
        g.rect(x+w*.24,y+h*.28,w*.52,h*.35)
        g.line(x+w*.27,y+h*.42,x+w*.73,y+h*.42,thick=1.3)
    else:
        for n in range(5):g.line(x+w*.18,y+h*.15+n*h*.035,x+w*.82,y+h*.15+n*h*.035,thick=.35)
        if kind in ['plc','safety','drive','io','light']:
            g.rect(x+w*.22,y+h*.42,w*.56,h*.17)
            g.circle(x+w*.18,y+h*.37,max(.8,min(1.5,w*.03)),GREEN)
        if kind in ['robot','ipc','switch','gateway']:
            for n in range(3):g.rect(x+w*(.14+.24*n),y+h*.49,w*.16,h*.13)
    for xx in [x+w*.25,x+w*.75]:
        g.circle(xx,y+h*.08,max(.7,min(1.5,w*.04)),fill=False)
        g.rect(xx-w*.1,y+h*.88,w*.2,h*.08)
    label=ident.replace('UNLOAD','UL-').replace('LOAD','LD-')
    fontsize=min(10,(w-2)/max(1,pdfmetrics.stringWidth(label,'CJK',1)))
    g.text(x+2,y-14,label,fontsize)


def panel_view(g,p,x,y,scale,lo=None,hi=None):
    pw,ph=p['width'],p['height'];lo=-pw/2 if lo is None else lo;hi=pw/2 if hi is None else hi
    w=(hi-lo)*scale;h=ph*scale
    px=lambda a:x+(a-lo)*scale
    py=lambda a:y+(ph/2-a)*scale
    g.rect(x,y,w,h);g.rect(x+3,y+3,w-6,h-6)
    dim(g,x,y-24,w,0,str(round(hi-lo)))
    dim(g,x-20,y,0,h,str(ph),True)
    for a in [-pw*.42,pw*.42]:
        for b in [-ph*.43,ph*.43]:
            if lo+8<a<hi-8:g.rect(px(a)-3,py(b)-6,6,12)
    # Wire ducts: faithful sizes/positions from the existing 3D controlPanel.
    for a in [-pw*.45,pw*.45]:
        if lo<a<hi:
            g.rect(px(a-12.5),py(ph*.425),25*scale,ph*.85*scale,stroke=CYAN)
    for row in p['rows']:
        total=sum(a['size'][0] for a in row['items'])+14*(len(row['items'])-1)
        left=-total/2;ry=row['y'];bottom=ry-max(a['size'][1] for a in row['items'])/2-13
        rail_l=max(lo+8,-total/2);rail_r=min(hi-8,total/2)
        if rail_r>rail_l:
            g.rect(px(rail_l),py(ry+17.5),(rail_r-rail_l)*scale,35*scale,stroke='#bc6c00')
        dl=max(lo+8,-pw*.435);dr=min(hi-8,pw*.435)
        g.rect(px(dl),py(bottom+9),(dr-dl)*scale,18*scale,stroke=CYAN)
        for spec in row['items']:
            dw,dh,_=spec['size'];cx=left+dw/2;left+=dw+14
            if cx-dw/2<lo or cx+dw/2>hi:continue
            device(g,px(cx-dw/2),py(ry+dh/2),dw*scale,dh*scale,spec['kind'],spec['id'])
    # Top terminal rail and twelve illustrative terminal bodies from the 3D.
    pitch=min(25,pw/18);ty=ph*.3
    for i in range(12):
        tx=(i-5.5)*pitch
        if lo<tx-pitch/2 and tx+pitch/2<hi:
            g.rect(px(tx-(pitch-2)/2),py(ty+15),(pitch-2)*scale,30*scale,stroke=BLUE)
            g.circle(px(tx),py(ty),1.2,fill=False)
    if lo<-pw*.35<hi:
        g.circle(px(-pw*.35),py(-ph*.36),4,fill=False);g.earth(px(-pw*.35),py(-ph*.36)+5)
    g.text(x,y+h+12,'背板正視／單位 mm；DIN 軌橙色、線槽青色、端子藍色。',9)


def panel_layout(g):
    sheets=0
    for p in g.d['panels']:
        sheets+=1;g.new('盤面配置 - '+p['profile'],'尺寸與元件包絡沿用既有 3D；散熱間距、線槽容量及加工孔位待原廠選型後確認。',code='P'+str(sheets))
        scale=min(1.0,940/p['width'],460/p['height'])
        panel_view(g,p,125,175,scale)
        if p['width']<650:
            g.text(730,178,'配置說明',16)
            y=215
            for text in ['背板：'+str(p['width'])+' × '+str(p['height'])+' mm','元件尺寸取自 3D 規劃包絡。','RC1 控制器另置承重層板，不掛 DIN 軌。','PE 接地柱與門板跨接不可省略。','電源與訊號分槽；現場線束於入口固定。','端子圖形數量沿用 3D 示意，施工數量依 I/O 清單擴充。']:
                y+=g.text(730,y,text,12,limit=355)+14
        g.notes(['本頁呈現現有安裝位置；QF3、K2、介面隔離等新增候選項尚未完成機構佈置。',
                 '桌板穿線孔、櫃體入口、護口及拉力固定見 3D；開孔孔徑與座標待線束外徑及鈑金圖定案。'],690)
        if p['width']>1800:
            # Large 3D panel overview plus readable half-panel details.
            for half,(lo,hi) in enumerate([(-p['width']/2,0),(0,p['width']/2)]):
                sheets+=1;g.new('盤面局部 - '+('左半部' if half==0 else '右半部'),'同一塊背板的局部放大；中心分界只作視圖切分，不代表新增隔板。',code='P'+str(sheets))
                panel_view(g,p,125,180,min(940/(hi-lo),.75),lo,hi)
                g.notes(['局部圖只繪完整落在此半部的元件；中央端子排及跨界元件以 P1 全景為準。',
                         '代號縮寫：LD-X/Z = LOADX/Z；UL-X/Z = UNLOADX/Z。完整軸號與回路見 400-409。'],695)
    extras=[c for c in g.d['components'] if c['id'] not in {i['id'] for p in g.d['panels'] for r in p['rows'] for i in r['items']}]
    if extras:
        sheets+=1;g.new('盤外與層板元件配置','盤外元件的功能位置與安裝方式示意；位置、孔距與維修淨空須由機構設計確認。',code='P'+str(sheets))
        for i,c in enumerate(extras):
            x=85+(i%2)*545;y=160+(i//2)*240
            g.text(x,y,c['id']+' / '+c['title'],14)
            if c['id']=='RC1':
                w,h=(420,200) if g.d['code']=='ACID' else (357,94)
                device(g,x+50,y+58,w*.65,h*.65,'robot',c['id'])
                yy=y+58+h*.65;g.rect(x+42,yy+4,w*.65+16,6)
                g.line(x+55,yy+10,x+55,yy+25);g.line(x+w*.65+25,yy+10,x+w*.65+25,yy+25)
                g.text(x,y+210,'控制器置固定層板；原廠線束留維修彎曲空間。',10)
            else:
                device(g,x+70,y+55,180,65,'io',c['id'])
                g.text(x,y+148,c['model'],11,limit=450)
        g.notes(['層板及盤外配置不代表新增電盤；實際設備位置請對照動畫。',g.d['notes'][0]],680)


def terminal(g,x,y,label):
    g.circle(x,y,2.5,fill=False);g.text(x+7,y-17,label,9,BLUE)


def analog_wiring(g,points):
    g.new('荷重元與量測輸入','AMP1 與 AI 模組尚未選型；下圖為外部供電放大器搭配相容差動量測輸入的功能規劃。',code='350')
    g.text(70,125,'LC-T2 / T2 荷重元',16)
    g.rect(80,201,205,244)
    for a,b,c,d in [(140,310,180,270),(180,270,220,310),(220,310,180,350),(180,350,140,310)]:g.line(a,b,c,d)
    g.text(105,225,'原廠電橋感測器',13)
    g.text(103,382,'激勵／差動訊號／屏蔽',10)
    g.text(104,403,'原廠線束，不接一般 DI',10)
    g.line(285,318,430,318);g.text(300,279,'OEM cable',11,GREEN)
    g.text(300,335,'多芯線束',10)
    g.rect(430,201,215,244);g.text(451,220,'AMP1* 放大器',16)
    g.text(443,308,'BRIDGE IN',10)
    g.text(544,302,'OUT +',10);g.text(544,363,'OUT -',10)
    g.text(458,408,'mV/V → 類比／數位*',11)
    g.line(475,145,475,201,BLUE);g.text(447,119,'+24 V*',11,BLUE)
    g.line(585,145,585,201,BLUE);g.text(564,119,'0 V*',11,BLUE)
    g.text(668,234,points[0]['function'],12)
    g.text(678,262,points[0]['wire']+' / 訊號對',11,GREEN)
    g.line(645,318,915,318);g.line(645,380,915,380)
    terminal(g,759,318,'XAI:01 / +');terminal(g,759,380,'XAI:02 / -')
    g.rect(915,201,192,244);g.text(936,222,'IO1 / AI*',16)
    g.text(930,308,points[0]['signal']+' / IN +',11);g.text(930,370,'IN - / REF*',11)
    g.text(928,412,'實際端子待模組選型',10)
    g.notes(['候選採 4-20 mA 或數位介面，二擇一；本頁只示意類比候選的訊號對，不可直接當最終接線。',
             '供電、主動／被動迴路、量測參考及屏蔽接地須由 AMP1 與 AI 模組手冊配對確認。',
             '荷重元原始電橋接 AMP1；電橋激勵與 mV/V 訊號不得直接 PLC 數位輸入。',
             points[0]['wire']+' 與 XAI:01/02 沿用 I/O 清單；AMP1 就緒訊號另見普通 DI 點表。'],530)


def point_wiring(g):
    for prefix,base,name in [('DI',200,'數位輸入'),('DO',300,'數位輸出'),('AI',350,'類比／量測輸入')]:
        points=[r for r in g.d['io'] if r['signal'].startswith(prefix)]
        if prefix=='AI' and points:
            analog_wiring(g,points)
            continue
        for start in range(0,len(points),8):
            rows=points[start:start+8]
            g.new(name+'接線 '+str(start//8+1),'每列對應一個規劃點；端子、線號及功能沿用上一版。原廠介面與隔離型式需依選型核定。',code=base+start//8)
            g.text(65,116,g.d.get('control','IO1'),12)
            g.rect(72,153,145,535)
            g.text(85,163,'IO1 / '+prefix,15)
            g.text(85,189,'功能端子',10)
            g.text(85,207,'模組料號待定',10)
            g.text(85,226,'非原廠腳位',10)
            g.line(275,141,1120,141,BLUE);g.line(275,162,1120,162,BLUE)
            g.text(780,118,'P24 / 受保護 +24 V',10,BLUE);g.text(985,167,'N24 / 0 V',10,BLUE)
            g.line(1090,141,1090,680,BLUE);g.line(1120,162,1120,680,BLUE)
            for i,r in enumerate(rows):
                y=285+i*49
                special='隔離' in r['circuit'] or prefix=='AI' or '類比' in r['circuit']
                g.text(90,y-12,r['signal'],12)
                terminal(g,217,y,'')
                g.line(217,y,790,y)
                g.text(285,y-34,r['function'],11,limit=485)
                g.text(365,y-14,r['wire'],9,GREEN)
                terminal(g,560,y,r['terminal'])
                if special:
                    g.rect(790,y-17,248,36)
                    g.text(802,y-13,'量測放大／原廠介面*' if prefix=='AI' else '隔離交握／控制器介面*',11)
                    g.text(802,y+3,'雙端規格／接頭與回路待定',8.5)
                elif prefix=='DI':
                    g.rect(790,y-17,230,36)
                    g.text(800,y-12,'OUT      B-'+r['signal'],10)
                    g.text(958,y-12,'BN / +',8);g.text(958,y+4,'BU / -',8)
                    g.line(1020,y-7,1090,y-7,BLUE);g.circle(1090,y-7,1.8,BLUE)
                    # 0 V route crosses +24 V with a visible gap (no junction).
                    g.line(1020,y+8,1086,y+8,BLUE);g.line(1094,y+8,1120,y+8,BLUE);g.circle(1120,y+8,1.8,BLUE)
                else:
                    g.rect(790,y-14,54,28);g.line(794,y+10,840,y-10)
                    g.text(860,y-13,'Y-'+r['signal']+' / 負載',10)
                    g.text(860,y+3,'抑制元件及極性待選',8.5)
                    g.line(844,y,855,y)
                    # uninterrupted return goes behind the annotation, not through it
                    g.line(855,y,855,y+22,BLUE);g.line(855,y+22,1086,y+22,BLUE);g.line(1094,y+22,1120,y+22,BLUE);g.circle(1120,y+22,1.8,BLUE)
            g.text(88,650,'M / COM：0 V',10,BLUE)
            g.text(88,667,'L+：保護後 24 V',9,BLUE)
            g.notes(['PNP 為一般感測／輸出負載的選型假設；隔離介面方框不代表把 24 V 直接接到遠端端口。',
                     '模組電源／COM 見 199 典型接線；安全輸入另見 105，與普通 I/O 分開。'],711)


def drive_wiring(g):
    axes=g.d['axes']
    for start in range(0,len(axes),3):
        g.new('驅動回路 '+str(start//3+1),'按軸分開標示保護、驅動、動力、回授及 PE；原廠腳位、馬達額定與回授型式尚待選定。',code=400+start//3)
        for n,a in enumerate(axes[start:start+3]):
            y=160+n*170;ident=a['id']
            g.text(65,y-23,ident+' / '+a['title'],14)
            g.text(65,y+11,'受控動力母線',10,MAGENTA)
            g.line(65,y+42,190,y+42,MAGENTA)
            g.contact(211,y+42,'QF-'+ident+'*',False)
            g.line(231,y+42,320,y+42,MAGENTA)
            g.rect(320,y,275,126)
            g.text(336,y+7,ident+' 驅動器',13)
            g.text(334,y+34,'PWR IN',9);g.text(515,y+34,'MOTOR',9)
            g.text(334,y+73,'CMD',9);g.text(515,y+73,'FEEDBACK',9)
            g.line(595,y+42,871,y+42,MAGENTA);g.text(625,y+21,'W-M-'+ident+' / 動力線束',10,GREEN)
            g.circle(900,y+42,29,fill=False);g.text(888,y+29,'M',18)
            g.text(949,y+26,'M-'+ident,12)
            g.line(595,y+83,900,y+83);g.line(900,y+83,900,y+71)
            g.text(625,y+64,'W-E-'+ident+' / 原廠回授',10,GREEN)
            g.line(930,y+42,1035,y+42,'#00a529');g.earth(1035,y+42)
            g.text(1047,y+37,'PE',10,'#00a529')
            g.line(65,y+83,320,y+83);g.text(65,y+63,'EC1 / 運動命令',10)
            g.line(65,y+113,320,y+113);g.text(65,y+93,'GC1 / 安全轉接*',10)
            g.text(337,y+105,'SAFE* / 原廠停止介面待確認',9)
        g.notes(['CMD 與安全線使用不同線束／端口；SAFE* 型式由最終驅動器及停止方案確認。',
                 'Z 軸可能採音圈或伺服；抱閘、防墜及停止策略需依機構與驅動器規格補齊。'],698)


def workstation_layout(g):
    g.new('工作站設備配置','此專案為影像軟體工作站，未定義機台電盤；依同一圖框繪製實體設備與走線示意。',code='P1')
    g.rect(110,545,970,18);g.line(145,563,145,663);g.line(1045,563,1045,663)
    device(g,195,295,145,250,'ipc','PC1 電腦')
    g.rect(460,260,300,185);g.rect(469,269,282,164);g.line(610,445,610,520);g.rect(555,520,110,25)
    g.text(467,236,'MON1 外接螢幕（選配）',14)
    g.rect(903,330,65,42);g.circle(935,350,13,fill=False);g.line(935,372,935,534);g.rect(900,534,70,10)
    g.text(835,300,'CAM1 USB 相機',13)
    g.line(903,350,863,350);g.line(863,350,863,505);g.line(863,505,340,505)
    g.text(727,480,'USB 原廠線材',10,GREEN)
    g.line(460,414,415,414);g.line(415,414,415,470);g.line(415,470,340,470)
    g.text(355,446,'HDMI / DP',10,GREEN)
    g.notes(['設備型號與尺寸尚未指定，本頁不標造作尺寸；相機也可使用電腦內建型式。',
             'PC／螢幕使用原廠電源；USB 相機由相容 USB 埠供電，不接機台 24 V。'],688)


def cad_power(g):
    g.new('主電源圖','AC 採單線功能圖，線條不代表相數；輸入制式、電壓、極數、容量及短路額定待確認。',code='100')
    g.text(70,127,'XAC / 現場 AC',14)
    terminal(g,130,175,'XAC:*');g.line(130,175,130,206,MAGENTA)
    # Disconnector shown as an open blade, distinct from its AC conductor.
    g.circle(130,213,2.5,fill=False);g.circle(130,248,2.5,fill=False)
    g.line(130,248,150,216);g.text(164,219,'QS1 總隔離開關',12)
    g.line(130,250,130,601,MAGENTA)
    for i,(ident,label) in enumerate([('QF1','控制電源'),('QF2','運動電源'),('QF3*','輔助／儀器電源')]):
        y=310+i*140;g.circle(130,y,2);g.line(130,y,280,y,MAGENTA)
        g.text(173,y-21,'W-AC-'+str(i+1),10,GREEN)
        g.contact(300,y,ident,False);g.line(320,y,420,y,MAGENTA)
        g.text(270,y+23,label,11)
        if i==0:
            g.rect(420,y-39,208,105);g.text(446,y-29,'PS1 / AC-DC',14)
            g.text(432,y-3,'AC IN',10);g.text(566,y-3,'+24 V',10);g.text(568,y+31,'0 V',10)
            g.line(628,y,850,y,BLUE);g.line(628,y+38,850,y+38,BLUE)
            g.text(700,y-21,'P24 → 101 / A3',11,GREEN);g.text(700,y+18,'N24 → 101 / A3',11,GREEN)
            g.line(451,y+66,451,y+84,'#00a529');g.earth(451,y+84);g.text(472,y+64,'PE',9,'#00a529')
        elif i==1:
            g.line(420,y,446,y,MAGENTA);g.contact(466,y,'K1',False);g.line(486,y,542,y,MAGENTA)
            g.contact(562,y,'K2*',False);g.line(582,y,715,y,MAGENTA)
            label='28 軸驅動／分支各自保護*' if g.d['code']=='PCB' else ('RC1 及 D1-D6／各自保護*' if g.d['code']=='MIL' else 'RC1 原廠電源入口')
            g.rect(715,y-23,378,66);g.text(730,y-12,label,13);g.text(730,y+13,'停止／再啟動允許見 105；安全介面待確認',10)
        else:
            g.rect(420,y-29,673,87);g.text(435,y-19,'AUX / 原廠電源及各分支保護*',13)
            g.text(435,y+6,g.d['aux'],11,limit=644)
    g.text(70,678,'XPE',12,'#00a529');g.line(125,687,1090,687,'#00a529')
    for x,label in [(210,'背板'),(425,'門板跨接'),(640,'設備機架'),(855,'Class I 外殼／馬達 PE')]:
        g.circle(x,687,2,'#00a529');g.earth(x,687);g.text(x+17,700,label,10,'#00a529')
    g.notes(['PE 不經隔離開關或熔絲；本圖不指定 0 V 與 PE 的連結，接地策略另行確認。'],746)
    g.new('24 VDC 電源分配','支路額定與線徑待負載表確認；控制、照明與現場負載分別保護。',code='101')
    g.text(66,136,'PS1 → P24 / +24 V',13,BLUE);g.text(66,163,'PS1 → N24 / 0 V',13,BLUE)
    g.line(270,152,1110,152,BLUE);g.line(270,179,1110,179,BLUE)
    loads=['GC1 安全控制',('IO1／序列介面' if g.d['code']=='ACID' else 'PLC1／IO1'), 'SW1 通訊',('REM1 隔離交握*' if g.d['code']=='ACID' else 'LC1 光源控制*'),'現場感測器*','閥島／燈號*']
    for i,label in enumerate(loads):
        x=93+i*173;y=350
        # Separate branch pair. Both rails extend left to cover all six groups.
        g.line(x+25,152,x+25,175,BLUE);g.line(x+25,183,x+25,249,BLUE)
        g.circle(x+25,152,2,BLUE)
        g.rect(x+19,249,12,40);g.line(x+25,249,x+25,289)
        g.text(x+38,258,'F'+str(i+1).zfill(2)+'*',10)
        g.line(x+25,289,x+25,y,BLUE);g.text(x+33,296,'W-P24-'+str(i+1),9,GREEN)
        g.line(x+119,179,x+119,y,BLUE);g.circle(x+119,179,2,BLUE)
        g.rect(x,y,146,108);g.text(x+8,y+10,'+24 V              0 V',9)
        g.text(x+8,y+40,label,12,limit=129);g.text(x+8,y+78,'額定待核對',10)
        terminal(g,x+25,330,'X24:'+str(i+1).zfill(2))
    g.line(92,152,270,152,BLUE);g.line(92,179,270,179,BLUE)
    g.text(70,522,'分配與端子規劃',15)
    g.notes(['F01-F06：電子支路保護／熔絲候選；接觸器與氣動安全功能見 105。',
             'X24、X0 為規劃端子群；線號顏色用於讀圖，不代表施工線材絕緣色。',
             'Remote、RS-485、SMEMA 等原廠介面另經相容隔離轉接，不以本頁 24 V 母線直接接入。',
             '控制電源保留診斷功能；閥島危險動作由獨立安全方案處理，不能只依 PLC 程式停機。'],563)
