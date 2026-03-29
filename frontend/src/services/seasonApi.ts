import { ApiError, api } from './api'

export interface JoinSeasonResponse {
  seasonId: number
  accountId: number
  isNewJoin: boolean
  initialCash: number
  availableCash: number
  frozenCash: number
  realizedPnl: number
}

export async function joinSeasonApi(seasonId: number): Promise<JoinSeasonResponse> {
  return api.post<JoinSeasonResponse>(`/v1/seasons/${seasonId}/join`)
}

export function shouldFallbackToMockSeason(error: unknown): boolean {
  if (error instanceof ApiError) {
    return (error.status === 404 && error.message === 'Not Found') || error.status >= 500
  }
  if (error instanceof TypeError) {
    return true
  }
  return false
}

export function extractSeasonApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback
  }
  if (error instanceof Error) {
    return error.message || fallback
  }
  return fallback
}
