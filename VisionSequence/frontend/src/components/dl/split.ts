/** 樣本分割（train/val/test）的循環切換：標記工作區狀態列的分割 chip 共用。 */
import type { DlSample } from '@/lib/types'

const SPLIT_CYCLE: DlSample['split'][] = ['', 'train', 'val', 'test']

export function nextSplit(current: DlSample['split']): DlSample['split'] {
  return SPLIT_CYCLE[(SPLIT_CYCLE.indexOf(current) + 1) % SPLIT_CYCLE.length]
}
