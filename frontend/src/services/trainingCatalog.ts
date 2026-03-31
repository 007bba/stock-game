import { DEFAULT_DEMO_SEASON_ID } from '../config/demoSeason'

export interface TrainingPreset {
  id: string
  title: string
  focus: string
  description: string
  symbolUniverse: string[]
  defaultSymbol: string
  dateRange: string
  tags: string[]
  seasonId: number
  startingCash: number
}

export const TRAINING_PRESETS: TrainingPreset[] = [
  {
    id: 'opening-breakout',
    title: '开盘强势股判断',
    focus: '观察开盘前三步和第一波拉升，练“该不该追”。',
    description: '适合用来训练高开承接、盘口犹豫和第一次加速时的买入纪律。',
    symbolUniverse: ['000547.SZ', '002792.SZ', '688125.SH', '002413.SZ'],
    defaultSymbol: '000547.SZ',
    dateRange: '历史片段 A · 2025-12',
    tags: ['历史回放', '开盘决策', '纪律训练'],
    seasonId: DEFAULT_DEMO_SEASON_ID,
    startingCash: 1000000,
  },
  {
    id: 'pullback-discipline',
    title: '回调低吸纪律',
    focus: '只在回调有承接时动手，练“忍”和“等确认”。',
    description: '用慢一点的节奏看价格回落、量能衰减和再次转强的时点。',
    symbolUniverse: ['601869.SH', '300377.SZ', '600345.SH', '600271.SH'],
    defaultSymbol: '601869.SH',
    dateRange: '历史片段 B · 2025-12',
    tags: ['回调买点', '仓位控制', '止损意识'],
    seasonId: DEFAULT_DEMO_SEASON_ID,
    startingCash: 1000000,
  },
  {
    id: 'close-review',
    title: '尾盘决策复盘',
    focus: '训练尾盘是否继续持有、减仓还是卖出的判断。',
    description: '更适合复盘自己是否追高、是否提前写清理由、是否按计划执行。',
    symbolUniverse: ['300710.SZ', '688205.SH', '002977.SZ', '003007.SZ'],
    defaultSymbol: '300710.SZ',
    dateRange: '历史片段 C · 2025-12',
    tags: ['尾盘处理', '复盘评分', '交易理由'],
    seasonId: DEFAULT_DEMO_SEASON_ID,
    startingCash: 1000000,
  },
]

export function getTrainingPresetById(id: string): TrainingPreset | null {
  return TRAINING_PRESETS.find((item) => item.id === id) ?? null
}
