"""Project-specific sheets using the repository's A3 CAD frame and symbols."""

def build(g):
    from cad_sheets import device, dim, point_wiring, drive_wiring
    d=g.d
    g.new('控制盤配置與穿線規劃','與3D同一份 control-plan.js；配置尺寸非原廠加工圖，施工前須核定散熱與維修間距。',code='P1')
    x,y,k=100,145,.76
    g.rect(x,y,620*k,660*k)
    dim(g,x,y-22,620*k,0,'620');dim(g,x-20,y,0,660*k,'660',True)
    px=lambda a:x+(a+310)*k
    py=lambda a:y+(330-a)*k
    for yy in [237,100,-45,-225]:
        g.rect(px(-275),py(yy+17.5),550*k,35*k)
        duct=-311 if yy==-225 else yy-66
        g.rect(px(-274),py(duct+10),548*k,20*k)
    for xx in [-291,291]:g.rect(px(xx-12.5),py(312),25*k,624*k)
    for a in d['devices']:
        cx,cy,_=a['at'];w,h,_=a['size']
        device(g,px(cx-w/2),py(cy+h/2),w*k,h*k,a['kind'],a['id'])
    g.text(110,py(322),'X24 / X0 / XDI / XDO',9)
    g.text(411,py(-305),'PE BUS',9)
    g.box(630,145,450,96,'盤內分區','上層：隔離、支路保護、24 V、安全\n中層：PLC、I/O、網路、共焦控制器\n下層：8 軸驅動、兩組光學模組及 IPC')
    g.box(630,270,450,116,'桌板穿線剖面（規劃）','700 × 500 × 4 板；開孔中心 X = ±290、Z = +231\n2 × Ø26 通孔，護口內徑 Ø20；位於花崗岩外側\n下通電盤，側邊固定支架承重；活動段保留服務環\n實際孔徑依線束填充率及接頭外徑重新核定')
    g.box(630,416,450,118,'整線與維修','動力與量測／網路分槽，交叉處儘量垂直\n光纖與CL-CV5遵守原廠最小彎曲半徑、固定方式\n移動端夾持外護套並保留鬆弛量；不可夾緊光纖芯\nCL-S015N 模組與感測頭配對，不得任意交換')
    g.text(636,564,'3D：電盤剖視／電盤透視／整線配置',13)
    g.text(636,591,'器件明細與線號見後續頁；電盤未做熱負載認證。',11)

    g.new('主電源與 24 V 分配','功能單線圖；電壓、相數、保護額定與電纜截面待廠務及負載表確認。',code='100')
    g.text(70,132,'XAC 現場 AC',14);g.line(90,170,1110,170,'#cb00c9')
    g.contact(210,170,'QS1',False)
    for xx,ident,target,sub in [(330,'QF1','PS1 / 24 VDC','控制電源；容量待負載核定'),(650,'QF2','K1 → 驅動支路','各軸另設支路保護／原廠停止介面'),(970,'QF3','IPC1 AC 電源','原廠電源；不經运动允許接點')]:
        g.line(xx,170,xx,235,'#cb00c9');g.contact(xx,235,ident,False)
        g.line(xx,235,xx,280,'#cb00c9');g.box(xx-125,280,250,88,target,sub)
    g.line(330,368,330,417,'#0039e6');g.line(100,417,1100,417,'#0039e6')
    g.text(80,389,'P24 / 支路保護後 +24 V；0 V 各自回 X0，不以 PE 代替',12)
    for xx,txt in [(175,'PLC1 / IO1 / SW1'),(470,'CL1 / LC1'),(765,'GC1 安全控制'),(1030,'YV / HL 現場負載')]:
        g.line(xx,417,xx,463,'#0039e6');g.box(xx-115,463,230,67,txt,'各支路設保護，額定待定')
    g.line(80,598,1100,598,'#00a529');g.earth(85,598)
    g.text(115,562,'PE：機架、門板跨接、背板、Class I 器件及馬達獨立接地；屏蔽依OEM要求',13)
    g.notes(['24 V 電源不可直接接感測頭；CL1 → CL-CV5 → OM1/OM2 → 配對感測頭。','K1 動力允許不等同安全功能完成；STO／抱閘及安全邏輯見105、400系列。'],650)

    g.new('安全與防墜功能圖','雙通道急停與門鎖獨立於普通PLC；安全等級、冗餘與停止時間待風險評估。',code='105')
    g.box(445,160,265,405,'GC1 安全控制器','測試脈衝／雙通道輸入\n人工復歸／EDM 回授\n輸出配置依最終機型核定')
    for yy,label in [(290,'ES1 急停 CH1 / CH2'),(395,'GS1 門鎖 CH1 / CH2')]:
        g.box(65,yy-35,255,85,label,'獨立通道，功能端子非原廠腳位')
        for off in [-8,15]:g.line(320,yy+off,445,yy+off)
    g.box(65,495,255,70,'RESET / EDM','復歸按鈕與外部回授');g.line(320,530,445,530)
    for yy,title,sub in [(285,'SAFE → 各驅動器','STO或原廠停止介面，禁止繞過'),(402,'K1 / 動力允許','接觸器方案／冗餘與回授待定'),(535,'DZ / DH 防墜','抱閘或機械保持，斷能前先保持')]:
        g.line(710,yy,805,yy);g.box(805,yy-28,295,83,title,sub)
    g.notes(['CL 量測就緒／異常屬普通交握，不是安全訊號。PLC 僅讀安全狀態，不能取代安全控制。','吸附保持／洩壓順序須防止斷氣掉件；動畫限力值與最小間隙未經實機驗證。'],650)

    g.new('共焦、視覺與運動通訊','報價套組不含已確認的 EtherCAT 擴充；CL以Ethernet資料＋隔離I/O交握規劃。',code='110')
    g.box(60,140,220,88,'CL1 / CL-3000','24 VDC ±10%\n2 模組配置')
    for yy,ident in [(300,'OM1 上頭'),(445,'OM2 下頭')]:
        g.line(170,228,170,yy+40);g.line(170,yy+40,370,yy+40)
        g.text(185,yy+12,'CL-CV5 原廠線',11)
        g.box(370,yy,250,88,ident+' / CL-S015N','與感測頭原廠配對')
        g.line(620,yy+44,830,yy+44);g.text(641,yy+15,'配對光纖',11)
        g.box(830,yy,270,88,'CL-S015 感測頭','參考距離15 mm；一般量程±1 mm')
    g.line(280,180,375,180);g.box(375,140,250,88,'SW1 / IPC1','Ethernet量測資料／PLC配方')
    g.line(625,180,830,180);g.box(830,140,270,88,'PLC1 / IO1','TIMING、READY、ERROR\n隔離介面與極性待核定')
    g.notes(['IPC1專用視覺網卡 → CAM-A／B／C；LC1控制照明，接口與觸發時序待相機選型。','PLC1 EtherCAT → DX、DZ、DT1、DT2、DR、DIN、DOUT、DH；各軸回授走原廠線。','OP-88864 是感測頭對置調整治具；工件夾持由ST1三爪及ST2環座完成。','狹口內底遮光、環帶可及性、兩頭同步及K值校正須樣品POC，不以動畫結果宣稱可量。'],582)
    # Shared reference-style, functional (non-OEM) terminal and axis drawings.
    from render import typical_io
    typical_io(g);point_wiring(g);drive_wiring(g)
    for start in range(0,len(d['devices']),12):
        g.new('元件表 '+str(start//12+1),'代號、數量與3D盤內配置一致；未報價器件為預算規劃，尺寸不作鑽孔依據。',code=600+start//12)
        rows=[[a['id'],a['title'],a['model'],'×'.join(str(v)for v in a['size'])] for a in d['devices'][start:start+12]]
        g.table(['代號','用途','型號／選型狀態','包絡 W×H×D'],rows,[90,270,510,220],size=11)
        g.text(55,714,'共焦套組含CL1、OM1/OM2、2頭、2線與調整治具；成本表僅按整組NT$420000未稅計一次。',10)

if __name__=='__main__':
    import sys,json
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'tools/circuit-drawings'))
    from render import Drawing
    g=Drawing(json.loads((root/'WorkpieceMeasurement/docs/electrical/circuit-data.json').read_text(encoding='utf-8')))
    build(g);g.save()
    (root/'TEMP/workpiece-artifacts/circuit-qa.json').write_text(json.dumps({'pages':g.pages,'errors':g.errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print(len(g.pages),'pages',len(g.errors),'layout errors')
    if g.errors:raise SystemExit(g.errors)
