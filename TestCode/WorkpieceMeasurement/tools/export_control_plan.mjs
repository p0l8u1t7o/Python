import fs from 'node:fs/promises';
import {PANEL,DEVICES,AXES,IO,LINKS} from '../web/js/control-plan.js';
const out=new URL('../docs/electrical/',import.meta.url);await fs.mkdir(out,{recursive:true});
const data={project:'WorkpieceMeasurement',code:'WPM',title:'杯體加工件 AOI＋共焦量測設備',revision:'1.1',date:'2026-09-29',status:'工程規劃／非施工放行',control:'PLC1 / IO1',panel:PANEL,devices:DEVICES,axes:AXES.map(([id,title])=>({id,title})),io:IO,links:LINKS,
 notes:['工件名稱與用途以使用者2026-09-29更正為準：杯體加工件，某機構的零件。','元件外形為3D安裝包絡，散熱、安裝孔、線徑、保護額定及原廠腳位待選型確認。','CL套組報價10817923未稅NT$420000；2026-08-31到期。供電24VDC，CL-CV5與配對光纖使用原廠線。','參考距離15mm；狹口量內底光路與量測精度待POC。OP-88864調整感測頭，工件另由夾头與薄環座承載。','安全門、急停接獨立安全控制器，普通PLC只監看；上頭避讓與垂直軸須防墜。'],
 added:['DH上頭避讓Z軸及H-UP/H-DN到位輸入。','實際桌板穿線開孔、護口、機櫃內盤、固定線槽與活動服務環。'],
 sources:['docs/quotation-summary.md','web/js/control-plan.js','web/js/spec.js','web/js/sequence.js'],references:[['CL-3000 controller','https://www.keyence.com.tw/products/measure/laser-1d/cl-3000/models/cl-3000/'],['CL-S015 / CL-S015N','https://www.keyence.com.tw/products/measure/laser-1d/cl-3000/models/cl-s015n/'],['OP-88864 adjustment fixture','https://www.keyence.com.tw/products/measure/laser-1d/cl-3000/models/op-88864/']]};
await fs.writeFile(new URL('circuit-data.json',out),JSON.stringify(data,null,2)+'\n');console.log('Exported control-plan: '+DEVICES.length+' devices, '+IO.length+' points, '+AXES.length+' axes');
