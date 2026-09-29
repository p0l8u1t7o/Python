import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const temp=path.resolve(project,'../TEMP/workpiece-artifacts');
const require=createRequire(path.join(temp,'package.json'));
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const filename=path.join(project,'docs/cost-estimate.xlsx');
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(filename));
await fs.mkdir(temp,{recursive:true});
if(process.argv.includes('--inspect')){
  console.log((await wb.inspect({kind:'sheet',include:'id,name'})).ndjson);
  console.log((await wb.inspect({kind:'table',range:'摘要!A1:C30',include:'values,formulas',tableMaxRows:30,tableMaxCols:3,maxChars:8000})).ndjson);
  const preview=await wb.render({sheetName:'摘要',range:'A1:C27',scale:1,format:'png'});
  await fs.writeFile(path.join(temp,'cost-before.png'),new Uint8Array(await preview.arrayBuffer()));
  console.log(JSON.stringify(wb.worksheets.getItem('明細').getUsedRange().values));
  process.exit(0);
}
const detail=wb.worksheets.getItem('明細'), summary=wb.worksheets.getItem('摘要');
const values=detail.getRange('A2:N42').values;
const row=code=>values.findIndex(v=>v[0]===code)+2;
const put=(sheet,cell,value)=>sheet.getRange(cell).values=[[value]];
const replace=(code,fields)=>{const r=row(code);for(const [col,v]of Object.entries(fields))put(detail,col+r,v);};
replace('3-01',{C:'共焦上下測厚報價套組',D:'1控制器＋2頭＋2光學模組＋2纜線＋1調整治具',E:'CL-3000 / CL-S015 / CL-S015N / CL-CV5 / OP-88864',F:'報價10817923整組價格；2026-08-31到期，採購前重詢',G:1,H:'套',I:420000,K:'A'});
replace('3-02',{C:'上頭避讓 Z 軸含驅動',D:'避讓30 mm；到位檢知、抱閘／防墜待選',E:'DH 精密電動滑台＋配套驅動器',F:'量測下降、移載前上升；不屬報價套組',G:1,H:'組',I:80000,K:'B'});
replace('3-03',{C:'替代光學方案預留（未選）',D:'狹口光路 POC 不成立時另議；不與套組重複採購',E:'型號與價格待重新詢價',F:'舊估價480000僅保留比較，不列基本方案',G:0,H:'組',I:480000,K:'C'});
replace('3-05',{C:'R 軸微動台＋手動 Z 調整台',D:'R 行程±3 mm；基準高度手動調整',F:'與新增 DH 自動避讓軸分開；剛性與重複性待驗證'});
replace('5-07',{D:'盤體配線、DIN軌、線槽、穿線孔護口、端子、調壓、真空',F:'包含3D規劃盤內輔件與整線，不重複加價'});
for(let r=2;r<=42;r++){
  detail.getRange(`J${r}`).formulas=[[`=G${r}*I${r}`]];
  detail.getRange(`L${r}`).formulas=[[`=J${r}*(1-VLOOKUP(K${r},'摘要'!$A$12:$B$14,2,FALSE))`]];
  detail.getRange(`M${r}`).formulas=[[`=J${r}*(1+VLOOKUP(K${r},'摘要'!$A$12:$B$14,2,FALSE))`]];
  if(values[r-2][13]===7)detail.getRange(`I${r}`).formulas=[[`='摘要'!${values[r-2][0]==='7-06'?'B6':'B5'}`]];
}
put(summary,'A1','杯體加工件 AOI＋共焦量測設備｜預算估算');
put(summary,'A2','2026-09-29 更新；TWD。共焦採歷史報價，其餘為內部估價。');
put(summary,'A3','人工擺盤、機內取放與量測；A／B／C 光路與精度須先完成 POC。');
put(summary,'C12','歷史報價／同級採購參考；重詢預留 ±10%');
for(const[r,f]of Object.entries({17:'=SUMIFS(\'明細\'!$J$2:$J$42,\'明細\'!$N$2:$N$42,"<7")',18:'=SUMIFS(\'明細\'!$J$2:$J$42,\'明細\'!$N$2:$N$42,7)',19:'=SUMIFS(\'明細\'!$J$2:$J$42,\'明細\'!$N$2:$N$42,8)',20:'=SUM(B17:B19)',21:'=B20*B7',22:'=B20+B21',23:'=SUM(\'明細\'!L2:L42)*(1+B7)',24:'=SUM(\'明細\'!M2:M42)*(1+B7)',25:'=B22*(1+B8)'}))summary.getRange('B'+r).formulas=[[f]];
const calc=wb.worksheets.getItem('選型計算');
calc.getRange('A8:D10').values=[['CL-S015 參考距離',15,'mm','KEYENCE CL-S015N 官方規格，非舊假設30/45 mm'],['CL-S015 一般量程（±）',1,'mm','官方規格；實際表面與內孔遮光须 POC'],['A／B／C 杯口光路','待驗證','—','移除未證實 NA 0.18/0.10；不得以中心射線宣稱可量']];
put(calc,'D11','5圈×3600點為模擬目標；CL取樣／觸發能力待配置核對');
put(calc,'B13',11.55);put(calc,'D13','B／OK約11.55秒，含上下頭避讓；驗收節拍待實測');
put(calc,'B15','待實測');put(calc,'D15','舊感測器估算不適用；需更新不確定度預算與 GR&R');
const comm=wb.worksheets.getItem('通訊架構');
comm.getRange('A5:E6').values=[['CL-3000','IPC1 / SW1','Ethernet＋隔離 I/O 交握','上下共焦距離資料與狀態','取樣同步、TIMING極性與資料格式待手冊核定'],['EtherCAT主站','8軸驅動器','EtherCAT（選型假設）','運動命令／回授','CL報價未含EtherCAT擴充，不放入此總線']];
const assumptions=wb.worksheets.getItem('假設與待確認');
put(assumptions,'B4','共焦套組使用報價10817923未稅420000元，2026-08-31已到期；其他為內部預算，皆須詢價確認。');
put(assumptions,'B7','正式名稱：杯體加工件；用途：某機構的零件。使用者2026-09-29更正AI規劃書誤稱，原始檔保留。');
put(assumptions,'B8','三規格均以CL-S015上下對置規劃；狹口遮光、環帶可及性、表面反射與精度待原廠樣品POC，尚未證明適用。');
put(assumptions,'B10','正常情境約11.4–11.6秒／件；異常重測另計。動畫不是實際產能承諾。');
let quote;try{quote=wb.worksheets.getItem('報價來源');}catch{}
if(!quote)quote=wb.worksheets.add('報價來源');
quote.getRange('A1:D13').values=[['共焦套組報價核對',null,null,null],['來源','Quotation_10817923_正奇精密科技股份有限公司.pdf','頁碼',1],['報價日期','2026-08-06','到期','2026-08-31'],['品號','用途','數量','單價'],['CL-3000','控制器',1,'整組報價，未拆價'],['CL-S015','感測頭',2,'已含套組'],['CL-S015N','光學模組',2,'已含套組'],['CL-CV5','原廠纜線',2,'已含套組'],['OP-88864','感測頭對置調整治具',1,'已含套組'],['套組未稅',420000,'NT$','僅此列计入明細3-01'],['稅率',0.05,'預算／報價核對',null],['稅金',null,'NT$',null],['含稅',null,'NT$',null]];
quote.getRange('B12').formulas=[['=B10*B11']];quote.getRange('B13').formulas=[['=B10+B12']];quote.getRange('B11').setNumberFormat('0%');quote.getRange('B10').setNumberFormat('#,##0');quote.getRange('B12:B13').setNumberFormat('#,##0');
quote.getRange('A1:D13').format.font.name='Microsoft JhengHei';quote.getRange('A1:D13').format.rowHeight=30;
for(const[c,w]of [['A',26],['B',62],['C',24],['D',30]])quote.getRange(c+':'+c).format.columnWidth=w;
quote.getRange('A4:D4').format.fill='#E8EEF6';quote.getRange('A1:D1').format.font.bold=true;
for(const sh of [detail,calc,comm,assumptions]){sh.getUsedRange().format.wrapText=true;sh.getUsedRange().format.rowHeight=52;}
summary.getRange('A1:C3').format.rowHeight=26;summary.getRange('A1:C1').merge();summary.getRange('A2:C2').merge();summary.getRange('A3:C3').merge();
summary.getRange('B17:B25').setNumberFormat('#,##0');summary.getRange('A22:C22').format.fill='#E8EEF6';summary.getRange('A25:C25').format.font.bold=true;
wb.recalculate();
const base=summary.getRange('B25').values[0][0];
if(Math.abs(base-7392315)>.01)throw Error('Unexpected budget '+base);
put(detail,'G'+row('3-01'),2);wb.recalculate();
if(Math.abs(summary.getRange('B25').values[0][0]-base-420000*1.15*1.05)>.01)throw Error('Quantity dependency failed');
put(detail,'G'+row('3-01'),1);wb.recalculate();
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#N/A|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:100},maxChars:2000})).ndjson);
for(const[name,range]of [['摘要','A1:C25'],['明細','A12:N18'],['選型計算','A1:D15'],['通訊架構','A1:E10'],['假設與待確認','A1:B11'],['報價來源','A1:D13']]){
 const preview=await wb.render({sheetName:name,range,scale:1,format:'png'});await fs.writeFile(path.join(temp,name+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(filename);
console.log(JSON.stringify({totals:summary.getRange('B17:B25').values,output:filename,quantityDependency:'pass'}));
