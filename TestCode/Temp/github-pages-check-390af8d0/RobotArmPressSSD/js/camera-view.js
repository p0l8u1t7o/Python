// Only use the wrist camera when it is holding an inspection pose.
// During pressing and travel its physical optical axis points away from the USB.
export function cameraSource(state, step, atPose) {
  return (state.station === 3 || state.station === 4) && state.shot !== ''
    && state.pressIds.length === 0 && !step.motion && atPose ? 'wrist' : 'global';
}

export function stationPreviewTime(sequence, station) {
  // A station shortcut should show the inspection, rather than freeze at the
  // first millisecond of the approach motion. Timeline/step controls stay exact.
  return station === 3
    ? sequence.steps.find(step => step.station === 3 && step.exposure).start
    : sequence.stationStart[station];
}

export const SENSOR_ASPECT = 13.2 / 8.8;
export function sensorViewport(width, height) {
  const h = Math.min(height, width / SENSOR_ASPECT), w = h * SENSOR_ASPECT;
  return { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h };
}
