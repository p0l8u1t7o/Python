/** Active simulation time excludes paused/tab-hidden time and caps frame stalls. */
export function advanceTime(time: number, dt: number, playing: boolean, speed = 1): number {
  return playing ? time + Math.max(0, Math.min(dt, 0.1)) * speed : time;
}

export function cyclePosition(time: number, steps: readonly { name: string; dur: number }[]) {
  const total = steps.reduce((sum, step) => sum + step.dur, 0);
  if (!steps.length || total <= 0) return { i: 0, p: 0, name: '', round: 0 };
  const local = time % total;
  let start = 0;
  for (let i = 0; i < steps.length; i++) {
    if (local < start + steps[i].dur) return { i, p: (local - start) / steps[i].dur, name: steps[i].name, round: Math.floor(time / total) };
    start += steps[i].dur;
  }
  return { i: 0, p: 0, name: steps[0].name, round: Math.floor(time / total) };
}
