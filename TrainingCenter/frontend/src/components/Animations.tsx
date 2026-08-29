import { motion } from 'framer-motion';

/**
 * 依 animation_key 播放 2D 機構動畫（SVG + framer-motion），
 * 讓新人快速理解元件「怎麼動」。
 */
export function MechanismAnimation({ animationKey }: { animationKey: string }) {
  switch (animationKey) {
    case 'cylinder':
      return <CylinderAnim />;
    case 'gripper':
      return <GripperAnim />;
    case 'robot-joint':
      return <RobotJointAnim />;
    case 'belt':
    case 'rollers':
    case 'carrier':
      return <BeltAnim rollers={animationKey === 'rollers'} />;
    case 'valve':
      return <ValveAnim />;
    case 'spin':
      return <SpinAnim />;
    case 'flow':
      return <FlowAnim />;
    case 'lift':
      return <LiftAnim />;
    case 'gantry':
      return <GantryAnim />;
    case 'flash':
    case 'blink':
      return <BlinkAnim />;
    case 'glow':
      return <GlowAnim />;
    default:
      return null;
  }
}

const loop = { repeat: Infinity, repeatType: 'reverse' as const, duration: 1.2, ease: 'easeInOut' as const };

function CylinderAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">氣缸：進氣 → 活塞桿伸出；換向 → 縮回</text>
      <rect x="40" y="40" width="120" height="30" rx="4" fill="#3a4a5a" stroke="#00cccc" />
      <motion.g animate={{ x: [0, 70] }} transition={loop}>
        <rect x="45" y="44" width="20" height="22" fill="#00cccc" />
        <rect x="65" y="52" width="140" height="6" fill="#bbb" />
      </motion.g>
      <motion.rect x="20" y="50" width="20" height="10" fill="#ffb100" animate={{ opacity: [1, 0.2] }} transition={loop} />
      <text x="15" y="90" fontSize="9" fill="#ffb100">壓縮空氣</text>
    </svg>
  );
}

function GripperAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">平行夾爪：兩指同步開閉夾持工件</text>
      <rect x="110" y="25" width="80" height="30" rx="4" fill="#3a4a5a" stroke="#00cccc" />
      <motion.rect x="115" y="55" width="14" height="35" fill="#00cccc" animate={{ x: [0, 22] }} transition={loop} />
      <motion.rect x="171" y="55" width="14" height="35" fill="#00cccc" animate={{ x: [0, -22] }} transition={loop} />
      <rect x="140" y="70" width="20" height="20" fill="#ffb100" />
    </svg>
  );
}

function RobotJointAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">關節：伺服馬達經減速機帶動連桿旋轉</text>
      <rect x="130" y="60" width="40" height="30" fill="#3a4a5a" />
      <motion.g style={{ originX: '150px', originY: '60px' }} animate={{ rotate: [-40, 40] }} transition={{ ...loop, duration: 2 }}>
        <rect x="145" y="15" width="10" height="45" rx="3" fill="#00cccc" />
        <circle cx="150" cy="18" r="6" fill="#ffb100" />
      </motion.g>
      <circle cx="150" cy="60" r="8" fill="#ffb100" />
    </svg>
  );
}

function BeltAnim({ rollers }: { rollers: boolean }) {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">{rollers ? '動力滾筒：各區段獨立驅動，載具零壓力累積' : '皮帶輸送：主動輪驅動皮帶帶動工件'}</text>
      {rollers ? (
        Array.from({ length: 9 }).map((_, i) => (
          <motion.g key={i} style={{ originX: `${40 + i * 28}px`, originY: '70px' }} animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.5, ease: 'linear' }}>
            <circle cx={40 + i * 28} cy="70" r="10" fill="#3a4a5a" stroke="#bbb" />
            <line x1={40 + i * 28} y1="60" x2={40 + i * 28} y2="80" stroke="#bbb" />
          </motion.g>
        ))
      ) : (
        <>
          <rect x="30" y="62" width="240" height="16" rx="8" fill="#2f6b3a" />
          <motion.g animate={{ x: [0, 40] }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}>
            {Array.from({ length: 7 }).map((_, i) => (
              <rect key={i} x={30 + i * 40} y="62" width="4" height="16" fill="#8fd19e" />
            ))}
          </motion.g>
        </>
      )}
      <motion.rect x="40" y="38" width="40" height="20" fill="#ffb100" animate={{ x: [0, 180] }} transition={{ repeat: Infinity, duration: 2.5, ease: 'linear' }} />
    </svg>
  );
}

function ValveAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">電磁閥：線圈通電 → 閥芯移動 → 切換氣／流體通路</text>
      <rect x="80" y="40" width="140" height="30" fill="#3a4a5a" stroke="#00cccc" />
      <motion.rect x="85" y="45" width="60" height="20" fill="#00cccc" animate={{ x: [0, 70] }} transition={loop} />
      <motion.rect x="230" y="40" width="30" height="30" fill="#ffb100" animate={{ opacity: [0.2, 1] }} transition={loop} />
      <text x="228" y="88" fontSize="9" fill="#ffb100">線圈</text>
      <motion.path d="M20 55 H80" stroke="#ffb100" strokeWidth="4" strokeDasharray="6 6" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 0.8, ease: 'linear' }} />
    </svg>
  );
}

function SpinAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">馬達／風扇／泵：旋轉輸出</text>
      <motion.g style={{ originX: '150px', originY: '60px' }} animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.5, ease: 'linear' }}>
        {[0, 90, 180, 270].map((a) => (
          <rect key={a} x="146" y="25" width="8" height="35" rx="4" fill="#00cccc" transform={`rotate(${a} 150 60)`} />
        ))}
      </motion.g>
      <circle cx="150" cy="60" r="8" fill="#ffb100" />
    </svg>
  );
}

function FlowAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">減壓閥：高壓入口 → 穩定低壓輸出</text>
      <motion.path d="M20 60 H120" stroke="#ff5a5a" strokeWidth="8" strokeDasharray="4 8" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 0.5, ease: 'linear' }} />
      <rect x="120" y="40" width="60" height="40" fill="#3a4a5a" stroke="#00cccc" />
      <motion.path d="M180 60 H280" stroke="#00cccc" strokeWidth="8" strokeDasharray="4 8" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 1.2, ease: 'linear' }} />
      <text x="30" y="85" fontSize="9" fill="#ff5a5a">35 bar</text>
      <text x="200" y="85" fontSize="9" fill="#00cccc">0.8 bar</text>
    </svg>
  );
}

function LiftAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">頂升移載：抬起載具 → 橫向送出</text>
      {Array.from({ length: 8 }).map((_, i) => (
        <circle key={i} cx={40 + i * 30} cy="75" r="8" fill="#3a4a5a" stroke="#bbb" />
      ))}
      <motion.g animate={{ y: [0, -20, -20, 0], x: [0, 0, 120, 120] }} transition={{ repeat: Infinity, duration: 3, times: [0, 0.3, 0.8, 1] }}>
        <rect x="70" y="62" width="60" height="6" fill="#00cccc" />
        <rect x="75" y="45" width="50" height="16" fill="#ffb100" />
      </motion.g>
    </svg>
  );
}

function GantryAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">XY 龍門：相機依拍攝點位移動</text>
      <rect x="30" y="30" width="240" height="60" fill="none" stroke="#3a4a5a" strokeDasharray="4 4" />
      <motion.rect x="30" y="45" width="240" height="6" fill="#3a4a5a" animate={{ y: [45, 75, 45] }} transition={{ repeat: Infinity, duration: 4 }} />
      <motion.g animate={{ x: [0, 200, 200, 0], y: [0, 0, 30, 30] }} transition={{ repeat: Infinity, duration: 4, ease: 'easeInOut' }}>
        <rect x="45" y="38" width="16" height="20" fill="#00cccc" />
        <motion.circle cx="53" cy="62" r="5" fill="#fff" animate={{ opacity: [0, 1, 0] }} transition={{ repeat: Infinity, duration: 1 }} />
      </motion.g>
    </svg>
  );
}

function BlinkAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">感測／光源：觸發時輸出訊號或閃光</text>
      <rect x="120" y="40" width="60" height="30" fill="#3a4a5a" stroke="#00cccc" />
      <motion.circle cx="150" cy="55" r="8" fill="#ffb100" animate={{ opacity: [0.1, 1], scale: [0.8, 1.3] }} transition={{ repeat: Infinity, duration: 0.8, repeatType: 'reverse' }} />
      <motion.path d="M180 55 H270" stroke="#ffb100" strokeWidth="3" strokeDasharray="6 6" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 0.8, ease: 'linear' }} />
    </svg>
  );
}

function GlowAnim() {
  return (
    <svg viewBox="0 0 300 100">
      <text x="10" y="18" fontSize="10" fill="#8a8a8a">電堆：H₂（陽極）+ O₂（陰極）→ 電 + 水 + 熱</text>
      <motion.path d="M20 45 H110" stroke="#ff5a5a" strokeWidth="6" strokeDasharray="4 8" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 0.7, ease: 'linear' }} />
      <motion.path d="M20 70 H110" stroke="#4aa3ff" strokeWidth="6" strokeDasharray="4 8" animate={{ strokeDashoffset: [0, -24] }} transition={{ repeat: Infinity, duration: 0.9, ease: 'linear' }} />
      <text x="22" y="40" fontSize="9" fill="#ff5a5a">H₂</text>
      <text x="22" y="85" fontSize="9" fill="#4aa3ff">空氣</text>
      <motion.rect x="110" y="30" width="80" height="55" fill="#3a4a5a" stroke="#00cccc" animate={{ stroke: ['#00cccc', '#ffb100'] }} transition={loop} />
      <motion.path d="M190 57 H280" stroke="#ffb100" strokeWidth="4" animate={{ opacity: [0.3, 1] }} transition={loop} />
      <text x="230" y="50" fontSize="9" fill="#ffb100">DC 電力</text>
    </svg>
  );
}
