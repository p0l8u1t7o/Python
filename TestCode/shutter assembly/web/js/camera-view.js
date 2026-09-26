// 子畫面來源：上視遠心相機（零件停在相機上方時）或手臂下視相機（其餘時間，顯示實際光軸看到的畫面）
export const cameraSource = state => (state.view === 'up' ? 'up' : 'down');

export function stationPreviewTime(sequence, station) {
  // 站別捷徑停在該站第一次取像，讓相機畫面有內容；時間軸與步驟選單仍精確定位
  const shot = sequence.steps.find(step => step.station === station && step.exposure);
  return shot ? shot.start + shot.dur * 0.5 : sequence.stationStart[station];
}

export const SENSOR_ASPECT = 2448 / 2048;   // IMX264 2/3"、5MP
export function sensorViewport(width, height) {
  const h = Math.min(height, width / SENSOR_ASPECT), w = h * SENSOR_ASPECT;
  return { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h };
}
