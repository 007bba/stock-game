import { create } from 'zustand'
import { loginMockUser, registerMockUser, type MockAuthUser } from '../services/mockAuth'

export type AuthMode = 'login' | 'register'

const SESSION_KEY = 'stock-game:auth-session'

function readSession(): MockAuthUser | null {
  if (typeof window === 'undefined') {
    return null
  }

  const sources = [localStorage, sessionStorage]
  for (const source of sources) {
    try {
      const raw = source.getItem(SESSION_KEY)
      if (!raw) {
        continue
      }
      const parsed = JSON.parse(raw) as MockAuthUser
      if (parsed?.id && parsed?.email) {
        return parsed
      }
    } catch {
      continue
    }
  }

  return null
}

function writeSession(user: MockAuthUser, remember: boolean): void {
  if (typeof window === 'undefined') {
    return
  }

  const payload = JSON.stringify(user)
  if (remember) {
    localStorage.setItem(SESSION_KEY, payload)
    sessionStorage.removeItem(SESSION_KEY)
    return
  }

  sessionStorage.setItem(SESSION_KEY, payload)
  localStorage.removeItem(SESSION_KEY)
}

function clearSession(): void {
  if (typeof window === 'undefined') {
    return
  }

  localStorage.removeItem(SESSION_KEY)
  sessionStorage.removeItem(SESSION_KEY)
}

interface AuthState {
  mode: AuthMode
  currentUser: MockAuthUser | null
  isLoading: boolean
  errorMessage: string | null
  setMode: (mode: AuthMode) => void
  clearError: () => void
  login: (params: { email: string; password: string; remember: boolean }) => Promise<void>
  register: (params: {
    email: string
    password: string
    displayName?: string
    remember: boolean
  }) => Promise<void>
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  mode: 'login',
  currentUser: readSession(),
  isLoading: false,
  errorMessage: null,

  setMode: (mode) => {
    set({ mode, errorMessage: null })
  },

  clearError: () => {
    set({ errorMessage: null })
  },

  login: async ({ email, password, remember }) => {
    set({ isLoading: true, errorMessage: null })

    try {
      const user = await loginMockUser({ email, password })
      writeSession(user, remember)
      set({ currentUser: user, isLoading: false })
    } catch (error) {
      const message = error instanceof Error ? error.message : '登录失败，请稍后再试'
      set({ errorMessage: message, isLoading: false })
      throw error
    }
  },

  register: async ({ email, password, displayName, remember }) => {
    set({ isLoading: true, errorMessage: null })

    try {
      const user = await registerMockUser({ email, password, displayName })
      writeSession(user, remember)
      set({ currentUser: user, isLoading: false })
    } catch (error) {
      const message = error instanceof Error ? error.message : '注册失败，请稍后再试'
      set({ errorMessage: message, isLoading: false })
      throw error
    }
  },

  logout: () => {
    clearSession()
    set({ currentUser: null, errorMessage: null, isLoading: false, mode: 'login' })
  },
}))
