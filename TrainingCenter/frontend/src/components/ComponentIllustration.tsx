/** 原創 SVG 類型示意，非實物照片或特定品牌／型號的外觀圖。 */
const RULES: [RegExp, string][] = [
  [/tank|儲槽|儲氣桶/i, 'tank'],
  [/cable.chain|拖鏈|slat.chain|鏈板/i, 'chain'],
  [/software|firmware|algorithm|program|軟體|韌體|演算法|程式|mes|scada|digital.twin|vision-guidance|bin-picking|fleet|gateway|hmi-ui/i, 'software'],
  [/light.curtain|光柵|光幕/i, 'curtain'],
  [/estop|emergency|急停/i, 'estop'],
  [/tower.light|三色|警示燈/i, 'tower'],
  [/camera|相機|鏡頭|lens/i, 'camera'],
  [/lighting|ring.light|backlight|光源/i, 'light'],
  [/calib|校正板/i, 'calibration'],
  [/frl|三點|過濾|filter|加濕|humidifier/i, 'filter'],
  [/valve|閥|speed.controller|節流/i, 'valve'],
  [/cylinder.sensor|感測|sensor|detector|encoder|rfid|變送|cvm|pressure.switch|laser.scanner|掃描器|load.cell|讀碼器/i, 'sensor'],
  [/cylinder|氣缸|氣壓缸|stopper|lift.locate|shock|緩衝器/i, 'cylinder'],
  [/gripper|夾爪|吸盤|vacuum.cup/i, 'gripper'],
  [/connector|fitting|coupler|接頭|cable.gland/i, 'connector'],
  [/ground|接地/i, 'ground'],
  [/tube|pipe|hose|管路|氣管|水管|inlet|dress.pack/i, 'pipe'],
  [/motor|servo|馬達|joint.servo/i, 'motor'],
  [/robot|scara|機械手臂|^j[1-6]|wrist|arm|手腕|腕部/i, 'robot'],
  [/conveyor|roller|輸送|滾筒|皮帶/i, 'conveyor'],
  [/plc|remote.i.o|remote.io|控制器|工業電腦|ipc|輸入.*輸出模組/i, 'plc'],
  [/hmi|觸控|螢幕|monitor|teach.pendant|教導器|示教器/i, 'screen'],
  [/switch|ethernet|交換器|通訊|communication|agv.dock/i, 'network'],
  [/breaker|contactor|relay|nfb|斷路|接觸器|繼電器/i, 'breaker'],
  [/power|psu|vfd|inverter|converter|電源|變頻|驅動器|整流|dcdc/i, 'power'],
  [/fuel.cell|stack|電堆|燃料電池|battery|電池/i, 'stack'],
  [/fan|pump|blower|風扇|風機|泵/i, 'fan'],
  [/rail|axis|screw|guide.shaft|導軌|滑軌|螺桿|線性|龍門/i, 'rail'],
  [/bearing|reducer|flange|brake|軸承|減速|法蘭|煞車|齒輪|coupling|聯軸器/i, 'bearing'],
  [/frame|fence|機架|護欄|圍籬/i, 'frame'],
  [/fixture|plate|carrier|tray|治具|定盤|載板|托盤|^base\b|side.guide|側導板/i, 'plate'],
];

function illustrationKind(identity: string, category: string): string {
  const match = RULES.find(([pattern]) => pattern.test(identity));
  if (match) return match[1];
  if (/soft|軟體/i.test(category)) return 'software';
  if (/接頭/.test(category)) return 'connector';
  if (/感測/.test(category)) return 'sensor';
  return 'generic';
}

function Shape({ kind }: { kind: string }) {
  switch (kind) {
    case 'tank': return <><rect x="100" y="38" width="100" height="110" rx="35" /><path d="M122 146v15m56-15v15M150 38V23h25M100 95H76v20" /><circle cx="180" cy="46" r="17" /><path d="m180 46 7-8" /><path d="M112 88h76" strokeDasharray="4 5" /></>;
    case 'chain': return <><path d="M48 134h150q50 0 50-44t-50-44h-76" fill="none" strokeWidth="25" />{[55, 84, 113, 142, 171, 200].map(x => <path key={x} d={`M${x} 120v28`} />)}<path d="M130 32v28m28-28v28m28-28v28m28-19-7 27m33-6-24 17m32 7h-27m15 32-23-14" /></>;
    case 'cylinder': return <><rect x="50" y="65" width="115" height="55" rx="5" /><path d="M60 65v55m90-55v55" /><path d="M165 86h75v13h-75" fill="#c6d8e3" /><path d="M70 65V48h18m45 17V48h-18" /><circle cx="76" cy="110" r="3" /><circle cx="141" cy="110" r="3" /></>;
    case 'motor': return <><path d="M60 60h115l25 20v50H60z" /><rect x="52" y="58" width="18" height="74" /><path d="M85 72v43m18-43v43m18-43v43m18-43v43m18-43v43" /><path d="M200 90h42v15h-42M78 130v12h110v-12" /><rect x="110" y="43" width="42" height="17" /></>;
    case 'conveyor': return <><rect x="32" y="67" width="236" height="52" rx="26" />{[58, 95, 132, 169, 206, 243].map(x => <circle key={x} cx={x} cy="93" r="16" />)}<path d="M55 120v30m190-30v30M96 45h90v22H96z" /></>;
    case 'camera': return <><rect x="66" y="51" width="112" height="85" rx="6" /><path d="M80 51V38h35v13M178 67h30v55h-30" /><ellipse cx="211" cy="94" rx="23" ry="31" /><ellipse cx="215" cy="94" rx="13" ry="20" fill="#0c2030" /><circle cx="85" cy="68" r="4" fill="#00cccc" /></>;
    case 'plc': return <><rect x="44" y="51" width="212" height="84" rx="4" />{[52, 111, 158, 205].map(x => <g key={x}><rect x={x} y="60" width="40" height="65" />{[70, 82, 94, 106].map(y => <circle key={y} cx={x + 10} cy={y} r="2" fill="#00cccc" />)}</g>)}<path d="M32 141h236" /></>;
    case 'screen': case 'software': return <><rect x="49" y="38" width="202" height="109" rx="7" /><rect x="61" y="50" width="178" height="82" fill="#0c2030" />{kind === 'software' ? <><path d="m120 71-23 20 23 20m60-40 23 20-23 20m-21-45-17 50" stroke="#00cccc" /></> : <><path d="M76 110h146M76 62v48m9-10 28-20 28 10 30-24 38 12" stroke="#00cccc" /><rect x="185" y="97" width="33" height="17" /></>}<path d="M126 148v13h48v-13" /></>;
    case 'sensor': return <><path d="M58 82h52v34H58zM110 70h83v58h-83z" /><path d="M68 116v28H41" /><rect x="175" y="76" width="18" height="46" fill="#00cccc" /><path d="M208 83q15 16 0 32m14-44q29 28 0 56" fill="none" strokeDasharray="4 5" /><circle cx="129" cy="85" r="4" fill="#ffb454" /></>;
    case 'connector': return <><path d="M46 83h36v34H46zM82 71h42v58H82zM124 80h51v40h-51zM175 68h43v64h-43zM218 82h35v36h-35z" /><path d="M90 77v46m12-46v46m85-47v49m12-49v49M47 91h25m-25 13h25m157-14h22m-22 14h22" /></>;
    case 'valve': return <><rect x="71" y="69" width="130" height="63" rx="4" /><rect x="201" y="76" width="43" height="48" /><path d="M83 69V51h30v18m39 0V51h30v18M89 133v19m47-19v19m45-19v19M115 69v63m43-63v63m-35-17 27-30m-27 0 27 30" /><circle cx="223" cy="89" r="4" fill="#00cccc" /></>;
    case 'filter': return <><path d="M43 59h214v21H43z" />{[66, 132, 198].map(x => <g key={x}><rect x={x} y="81" width="35" height="62" rx="12" /><path d={`M${x + 17} 143v13`} /></g>)}<circle cx="149" cy="53" r="20" /><path d="m149 53 9-10" /><path d="M72 96v30m132-30v30" /></>;
    case 'gripper': return <><rect x="110" y="39" width="80" height="64" rx="4" /><path d="M110 91H80v57h39v-16H99v-24h11m80-17h30v57h-39v-16h20v-24h-11" /><path d="M134 39V25m30 14V25" /><rect x="132" y="122" width="36" height="32" strokeDasharray="5 5" /></>;
    case 'robot': return <><path d="M66 151h78l-9-24H78zM96 129V89l63-42 53 42-15 20-40-30-35 25v25" /><circle cx="107" cy="93" r="17" /><circle cx="160" cy="61" r="17" /><circle cx="202" cy="97" r="13" /><path d="m211 108 20 12m-5-16 14 13-10 15" /></>;
    case 'tower': return <><path d="M126 151h48m-24 0v-39" />{['#ee6677', '#ffb454', '#00cccc'].map((color, i) => <rect key={color} x="128" y={31 + i * 27} width="44" height="27" rx="4" fill={color} />)}</>;
    case 'estop': return <><path d="m88 97 66-25 63 28v40l-64 24-65-27z" fill="#c49339" /><ellipse cx="151" cy="97" rx="43" ry="19" /><path d="M114 64v26c0 22 74 22 74 0V64" fill="#c84252" /><ellipse cx="151" cy="63" rx="37" ry="17" fill="#ee6677" /></>;
    case 'curtain': return <><rect x="62" y="28" width="21" height="132" fill="#c49339" /><rect x="217" y="28" width="21" height="132" fill="#c49339" />{[45, 65, 85, 105, 125, 145].map(y => <path key={y} d={`M84 ${y}h132`} stroke="#ee6677" strokeDasharray="6 5" />)}</>;
    case 'light': return <><ellipse cx="150" cy="94" rx="73" ry="54" /><ellipse cx="150" cy="94" rx="38" ry="28" fill="#0c2030" />{Array.from({ length: 12 }, (_, i) => <circle key={i} cx={150 + 56 * Math.cos(i * Math.PI / 6)} cy={94 + 41 * Math.sin(i * Math.PI / 6)} r="5" fill="#ffe7a2" />)}</>;
    case 'calibration': return <>{Array.from({ length: 6 }, (_, x) => Array.from({ length: 4 }, (_, y) => <rect key={`${x}-${y}`} x={72 + x * 26} y={42 + y * 26} width="26" height="26" stroke="none" fill={(x + y) % 2 ? '#c6d8e3' : '#263f50'} />))}</>;
    case 'ground': return <><path d="M150 38v65m-59 0h118m-99 18h80m-61 18h42m-25 18h10" stroke="#00cccc" strokeWidth="7" /><circle cx="150" cy="40" r="10" /></>;
    case 'pipe': return <><path d="M56 143V70q0-22 22-22h102q23 0 23 23v49h41" fill="none" strokeWidth="18" /><path d="M42 116h28m106-81v26m52 44v30" stroke="#00cccc" strokeWidth="7" /></>;
    case 'network': return <><rect x="46" y="60" width="208" height="73" rx="5" />{[60, 97, 134, 171, 208].map(x => <g key={x}><rect x={x} y="89" width="25" height="25" fill="#0c2030" /><circle cx={x + 5} cy="76" r="3" fill="#00cccc" /></g>)}</>;
    case 'breaker': return <>{[85, 128, 171].map(x => <g key={x}><rect x={x} y="39" width="43" height="113" rx="3" /><circle cx={x + 21} cy="52" r="5" /><rect x={x + 9} y="76" width="25" height="37" fill="#0c2030" /><circle cx={x + 21} cy="139" r="5" /></g>)}<path d="M93 86h112v12H93z" fill="#00cccc" /></>;
    case 'power': return <><rect x="90" y="32" width="120" height="127" rx="4" />{[53, 66, 79, 92].map(y => <path key={y} d={`M104 ${y}h68`} />)}<path d="m154 102-17 23h19l-10 21" stroke="#ffb454" /><circle cx="194" cy="50" r="4" fill="#00cccc" /></>;
    case 'stack': return <>{[0, 1, 2, 3, 4, 5, 6, 7].map(i => <path key={i} d={`m${60 + i * 18} 60 23-16v86l-23 16z`} />)}<path d="M69 72h151M69 124h151" stroke="#00cccc" /></>;
    case 'fan': return <><rect x="86" y="31" width="128" height="128" rx="8" /><circle cx="150" cy="95" r="50" />{[0, 90, 180, 270].map(angle => <path key={angle} d="M150 95q-50-12-18-43 30-3 18 43" transform={`rotate(${angle} 150 95)`} fill="#487083" />)}<circle cx="150" cy="95" r="12" fill="#00cccc" /></>;
    case 'rail': return <><path d="m38 115 185-64 26 19-185 64zM38 133l26 19 185-64V70M64 134v18" /><path d="m112 85 50-17 29 23-50 18-29-24v26l29 21 50-18V91" fill="#487083" /><circle cx="145" cy="86" r="4" /></>;
    case 'bearing': return <><ellipse cx="150" cy="95" rx="70" ry="61" /><ellipse cx="150" cy="95" rx="33" ry="29" fill="#0c2030" />{Array.from({ length: 8 }, (_, i) => <circle key={i} cx={150 + 51 * Math.cos(i * Math.PI / 4)} cy={95 + 44 * Math.sin(i * Math.PI / 4)} r="8" fill="#c6d8e3" />)}</>;
    case 'frame': return <><path d="M61 149V60l57-27h122v94l-58 28H61V60h121v95m0-95 58-27M118 33v94H61m57 0 64 28" fill="none" strokeWidth="7" /><path d="M63 103h119l56-28" /></>;
    case 'plate': return <><path d="m43 109 153-60 64 41-153 63zM43 109v12l64 43 153-61V90M107 153v11" />{[0, 1, 2, 3].map(i => <g key={i}><ellipse cx={86 + i * 33} cy={105 - i * 13} rx="5" ry="3" /><ellipse cx={112 + i * 33} cy={122 - i * 13} rx="5" ry="3" /></g>)}</>;
    default: return <><path d="m89 68 60-31 63 32v68l-61 28-62-29zM89 68l62 30 61-29m-61 29v67" /><path d="m118 53 62 30v28" stroke="#00cccc" /><text x="150" y="183" textAnchor="middle" fill="#9bb7c7" stroke="none" fontSize="12">元件類型待補</text></>;
  }
}

export function ComponentIllustration({ name, identity, category }: { name: string; identity: string; category: string }) {
  const kind = illustrationKind(identity.trim(), category);
  return (
    <svg viewBox="0 0 300 200" role="img" aria-label={`${name}：${kind === 'generic' ? '通用元件' : '元件類型'}示意圖，非實物照片`}>
      <rect width="300" height="200" fill="#0c2030" />
      <path d="M25 165h250M25 30v135" stroke="#203746" fill="none" />
      <g fill="#29495c" stroke="#a2c4d6" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"><Shape kind={kind} /></g>
    </svg>
  );
}
