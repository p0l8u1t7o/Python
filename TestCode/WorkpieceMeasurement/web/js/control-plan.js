// Shared by the 3D cabinet, drawing register and cost reconciliation.
// Sizes are installation envelopes, not OEM drilling dimensions.
const item = (id, kind, title, size, model, category = 'dc') => ({ id, kind, title, size, model, category, role: kind, description: title + '；外形為配置包絡，接腳與散熱間距待原廠圖面核定。' });
export const PANEL = { width: 620, height: 660, center: [0, 430, -221], profile: '杯體加工件量測控制盤' };
export const AXES = [
  ['DX', '移載 X'], ['DZ', '移載 Z'], ['DT1', 'ST1 旋轉'], ['DT2', 'ST2 旋轉'],
  ['DR', 'ST2 徑向'], ['DIN', '入料梭台'], ['DOUT', '出料梭台'], ['DH', '上感測頭避讓 Z'],
];
export const ROWS = [
  { y: 237, items: [
    item('QS1','isolator','總電源隔離',[36,65,65],'額定待負載確認','ac'),
    item('QF1','breaker','控制支路保護',[36,65,65],'型號待選','ac'),
    item('QF2','breaker','驅動支路保護',[36,65,65],'型號待選','ac'),
    item('QF3','breaker','IPC 支路保護',[36,65,65],'型號待選','ac'),
    item('PS1','psu','24 V 電源',[65,85,100],'24 VDC 容量待負載表','ac'),
    item('GC1','safety','安全控制器',[60,90,95],'GC-1000 規劃平台','safety'),
    item('K1','contactor','動力允許接觸器',[45,65,70],'型號與冗餘方案待定','safety'),
  ]},
  { y: 100, items: [
    item('PLC1','plc','設備 PLC',[100,85,85],'KV-X + EtherCAT 規劃平台'),
    item('IO1','io','現場 I/O',[65,80,65],'PNP 功能配置，模組待選'),
    item('SW1','switch','工業網路交換器',[40,80,70],'100/1000BASE-T','network'),
    item('LC1','light','相機光源控制器',[70,70,70],'三通道以上，型號待選'),
    item('CL1','gateway','共焦控制器',[70,85,100],'KEYENCE CL-3000'),
  ]},
  { y: -45, items: AXES.map(([id,title])=>item(id,'drive',title+' 驅動器',[45,95,110],'原廠配套，功率與回授待定','ac')) },
  { y: -225, items: [
    item('OM1','gateway','上頭光學模組',[100,140,140],'KEYENCE CL-S015N','signal'),
    item('OM2','gateway','下頭光學模組',[100,140,140],'KEYENCE CL-S015N','signal'),
    item('IPC1','ipc','視覺工業電腦',[150,95,130],'GPU / GigE 相機介面','network'),
  ]},
];
export const DEVICES = ROWS.flatMap(row=>{
  let x=-(row.items.reduce((n,i)=>n+i.size[0],0)+14*(row.items.length-1))/2;
  return row.items.map(d=>{const at=[x+d.size[0]/2,row.y,16];x+=d.size[0]+14;return {...d,at};});
});
export const IO = [
  ['DI','真空建立','VAC1'], ['DI','氣壓正常','AIR1'], ['DI','夾頭夾紧確認','CH1'], ['DI','夾頭鬆開確認','CH2'],
  ['DI','上頭避讓到位','H-UP'], ['DI','上頭量測位到位','H-DN'], ['DI','CL 準備完成','CL1 READY'], ['DI','CL 異常','CL1 ERROR'],
  ['DI','入料托盤存在','TR-IN'], ['DI','出料托盤存在','TR-OUT'],
  ['DO','真空吸附','YV1'], ['DO','破真空','YV2'], ['DO','貼靠前進','YV3'], ['DO','夾頭夾緊','YV4'],
  ['DO','CL 量測請求','CL1 TIMING'], ['DO','綠燈','HL-G'], ['DO','黃燈','HL-Y'], ['DO','紅燈','HL-R'],
].map(([type,title,target],i,all)=>{const n=all.slice(0,i).filter(r=>r[0]===type).length;return {signal:type+String(n).padStart(2,'0'),terminal:'X'+type+':'+String(n+1).padStart(2,'0'),wire:'W-'+type+String(n).padStart(2,'0'),function:title+' / '+target,circuit:target.startsWith('CL1')?'原廠介面／極性核對後隔離交握':'24 V PNP 規劃；型號待選'};});
export const LINKS = [
  ['PLC1','SW1 / IPC1','配方、取像請求、完成與結果'],
  ['CL1 / CL-3000','SW1 / IPC1','Ethernet 量測資料；不假定報價含 EtherCAT 擴充'],
  ['CL1','OM1 / OM2','2 × CL-CV5 原廠線；非普通 Ethernet 線'],
  ['OM1','上 CL-S015','配對光纖／感測頭；不得任意互換'],
  ['OM2','下 CL-S015','配對光纖／感測頭；保留維修彎曲空間'],
  ['IPC1','CAM-A / CAM-B / CAM-C','相機資料各走專用視覺網路'],
  ['PLC1 / IO1','LC1 / YV1-4','光源交握、真空及夾持閥控制'],
  ['PLC1 EtherCAT','DX DZ DT1 DT2 DR DIN DOUT DH','8 個規劃軸；DH 為本次避讓軸'],
];
