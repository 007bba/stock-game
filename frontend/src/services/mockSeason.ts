export type SeasonStatus = '报名中' | '进行中' | '已结束'

export interface MockSeason {
  id: number
  name: string
  status: SeasonStatus
  participants: number
  stockCount: number
  initialCash: number
  createdBy: string
  createdAt: string
  startDate: string
  endDate: string
}

export interface LobbySeason extends MockSeason {
  joined: boolean
}

const SEASONS_KEY = 'stock-game:mock-seasons'
const JOIN_MAP_KEY = 'stock-game:mock-season-joins'

const defaultSeasons: MockSeason[] = [
  {
    id: 1,
    name: 'S1 春季赛',
    status: '进行中',
    participants: 128,
    stockCount: 30,
    initialCash: 1000000,
    createdBy: 'System',
    createdAt: '2026-03-01T08:00:00.000Z',
    startDate: '2026-03-10',
    endDate: '2026-04-20',
  },
  {
    id: 2,
    name: 'S2 夏季赛',
    status: '报名中',
    participants: 74,
    stockCount: 20,
    initialCash: 800000,
    createdBy: 'System',
    createdAt: '2026-03-20T10:00:00.000Z',
    startDate: '2026-04-25',
    endDate: '2026-06-01',
  },
  {
    id: 3,
    name: 'S0 测试赛季',
    status: '已结束',
    participants: 42,
    stockCount: 10,
    initialCash: 500000,
    createdBy: 'QA',
    createdAt: '2026-02-01T09:00:00.000Z',
    startDate: '2026-02-10',
    endDate: '2026-03-01',
  },
]

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') {
    return fallback
  }

  try {
    const raw = localStorage.getItem(key)
    if (!raw) {
      return fallback
    }
    const parsed = JSON.parse(raw) as T
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

function writeJson<T>(key: string, value: T): void {
  if (typeof window === 'undefined') {
    return
  }
  localStorage.setItem(key, JSON.stringify(value))
}

function readSeasons(): MockSeason[] {
  const seasons = readJson<MockSeason[]>(SEASONS_KEY, [])
  if (seasons.length > 0) {
    return seasons
  }
  writeJson(SEASONS_KEY, defaultSeasons)
  return defaultSeasons
}

function writeSeasons(seasons: MockSeason[]): void {
  writeJson(SEASONS_KEY, seasons)
}

function readJoinMap(): Record<string, string[]> {
  return readJson<Record<string, string[]>>(JOIN_MAP_KEY, {})
}

function writeJoinMap(joinMap: Record<string, string[]>): void {
  writeJson(JOIN_MAP_KEY, joinMap)
}

function withJoinedFlag(seasons: MockSeason[], userId?: string): LobbySeason[] {
  const joinMap = readJoinMap()
  return seasons
    .slice()
    .sort((a, b) => b.id - a.id)
    .map((season) => ({
      ...season,
      joined: !!userId && (joinMap[String(season.id)] ?? []).includes(userId),
    }))
}

export async function listMockSeasons(userId?: string): Promise<LobbySeason[]> {
  await wait(180)
  const seasons = readSeasons()
  return withJoinedFlag(seasons, userId)
}

export async function createMockSeason(params: {
  name: string
  initialCash: number
  stockCount: number
  startDate: string
  endDate: string
  createdBy: string
  userId?: string
}): Promise<LobbySeason> {
  await wait(220)

  const seasons = readSeasons()
  const nextId = seasons.length > 0 ? Math.max(...seasons.map((item) => item.id)) + 1 : 1

  const newSeason: MockSeason = {
    id: nextId,
    name: params.name,
    status: '报名中',
    participants: 1,
    stockCount: params.stockCount,
    initialCash: params.initialCash,
    createdBy: params.createdBy,
    createdAt: new Date().toISOString(),
    startDate: params.startDate,
    endDate: params.endDate,
  }

  seasons.push(newSeason)
  writeSeasons(seasons)

  if (params.userId) {
    const joinMap = readJoinMap()
    joinMap[String(newSeason.id)] = [params.userId]
    writeJoinMap(joinMap)
  }

  return {
    ...newSeason,
    joined: true,
  }
}

export async function joinMockSeason(params: {
  seasonId: number
  userId: string
}): Promise<{ season: LobbySeason; isNewJoin: boolean }> {
  await wait(180)

  const seasons = readSeasons()
  const seasonIndex = seasons.findIndex((item) => item.id === params.seasonId)
  if (seasonIndex < 0) {
    throw new Error('赛季不存在或已删除')
  }

  const joinMap = readJoinMap()
  const key = String(params.seasonId)
  const userIds = new Set(joinMap[key] ?? [])
  const isNewJoin = !userIds.has(params.userId)

  if (isNewJoin) {
    userIds.add(params.userId)
    joinMap[key] = [...userIds]
    writeJoinMap(joinMap)

    seasons[seasonIndex] = {
      ...seasons[seasonIndex],
      participants: seasons[seasonIndex].participants + 1,
    }
    writeSeasons(seasons)
  }

  return {
    season: {
      ...seasons[seasonIndex],
      joined: true,
    },
    isNewJoin,
  }
}
