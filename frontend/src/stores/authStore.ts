import type { Session, User } from '@supabase/supabase-js'
import { create } from 'zustand'
import { supabase } from '../services/supabase'

export type AuthMode = 'login' | 'register'

export interface AuthUser {
  id: string
  email: string
  displayName: string
  createdAt: string
}

function normalizeEmail(email: string | null | undefined): string {
  return (email ?? '').trim().toLowerCase()
}

function inferDisplayName(user: User): string {
  const metadataName = user.user_metadata?.display_name
  if (typeof metadataName === 'string' && metadataName.trim()) {
    return metadataName.trim()
  }

  const email = normalizeEmail(user.email)
  const localName = email.split('@')[0]
  if (localName) {
    return localName
  }

  return 'player'
}

function toAuthUser(user: User | null): AuthUser | null {
  if (!user) {
    return null
  }

  return {
    id: user.id,
    email: normalizeEmail(user.email),
    displayName: inferDisplayName(user),
    createdAt: user.created_at,
  }
}

function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

let authListenerRegistered = false

interface AuthState {
  mode: AuthMode
  currentUser: AuthUser | null
  session: Session | null
  isLoading: boolean
  isInitialized: boolean
  errorMessage: string | null
  setMode: (mode: AuthMode) => void
  clearError: () => void
  initialize: () => Promise<void>
  getAccessToken: () => Promise<string | null>
  login: (params: { email: string; password: string; remember: boolean }) => Promise<void>
  register: (params: { email: string; password: string; displayName?: string; remember: boolean }) => Promise<{ needsEmailConfirmation: boolean }>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  mode: 'login',
  currentUser: null,
  session: null,
  isLoading: false,
  isInitialized: false,
  errorMessage: null,

  setMode: (mode) => {
    set({ mode, errorMessage: null })
  },

  clearError: () => {
    set({ errorMessage: null })
  },

  initialize: async () => {
    set({ isLoading: true, errorMessage: null })

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession()

      set({
        session,
        currentUser: toAuthUser(session?.user ?? null),
        isInitialized: true,
        isLoading: false,
      })

      if (!authListenerRegistered) {
        authListenerRegistered = true
        supabase.auth.onAuthStateChange((_event, nextSession) => {
          set({
            session: nextSession,
            currentUser: toAuthUser(nextSession?.user ?? null),
            isInitialized: true,
          })
        })
      }
    } catch (error) {
      set({
        errorMessage: toErrorMessage(error, '初始化登录态失败'),
        isInitialized: true,
        isLoading: false,
      })
    }
  },

  getAccessToken: async () => {
    const {
      data: { session },
    } = await supabase.auth.getSession()
    return session?.access_token ?? null
  },

  login: async ({ email, password, remember: _remember }) => {
    void _remember
    set({ isLoading: true, errorMessage: null })

    try {
      const { data, error } = await supabase.auth.signInWithPassword({ email: normalizeEmail(email), password })
      if (error) {
        throw error
      }

      set({
        session: data.session,
        currentUser: toAuthUser(data.user),
        isLoading: false,
        isInitialized: true,
      })
    } catch (error) {
      const message = toErrorMessage(error, '登录失败，请稍后再试')
      set({ errorMessage: message, isLoading: false })
      throw error
    }
  },

  register: async ({ email, password, displayName, remember: _remember }) => {
    void _remember
    set({ isLoading: true, errorMessage: null })

    try {
      const { data, error } = await supabase.auth.signUp({
        email: normalizeEmail(email),
        password,
        options: {
          data: {
            display_name: displayName?.trim() ?? '',
          },
        },
      })

      if (error) {
        throw error
      }

      const needsEmailConfirmation = !data.session

      set({
        session: data.session,
        currentUser: toAuthUser(data.user),
        isLoading: false,
        isInitialized: true,
      })

      return { needsEmailConfirmation }
    } catch (error) {
      const message = toErrorMessage(error, '注册失败，请稍后再试')
      set({ errorMessage: message, isLoading: false })
      throw error
    }
  },

  logout: async () => {
    set({ isLoading: true, errorMessage: null })

    try {
      const { error } = await supabase.auth.signOut()
      if (error) {
        throw error
      }

      set({
        currentUser: null,
        session: null,
        errorMessage: null,
        isLoading: false,
        isInitialized: true,
        mode: 'login',
      })
    } catch (error) {
      const message = toErrorMessage(error, '退出登录失败，请稍后再试')
      set({ errorMessage: message, isLoading: false })
      throw error
    }
  },
}))
