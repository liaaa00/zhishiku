import { defineStore } from 'pinia'

export interface AuthUser {
  id?: string
  username?: string
  is_admin?: boolean
  is_active?: boolean
  [key: string]: unknown
}

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem('user')
    return raw ? JSON.parse(raw) : null
  } catch {
    localStorage.removeItem('user')
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: readStoredUser() as AuthUser | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isAdmin: (state) => Boolean(state.user?.is_admin),
  },
  actions: {
    setToken(token: string | null | undefined) {
      this.token = token || ''
      if (this.token) localStorage.setItem('token', this.token)
      else localStorage.removeItem('token')
    },
    setUser(user: AuthUser | null | undefined) {
      this.user = user || null
      if (this.user) localStorage.setItem('user', JSON.stringify(this.user))
      else localStorage.removeItem('user')
    },
    setAuthPayload(payload: { token?: string | null; user?: AuthUser | null } | null | undefined) {
      if (payload?.token !== undefined) this.setToken(payload.token)
      if (payload?.user !== undefined) this.setUser(payload.user)
    },
    clearAuth() {
      this.setToken(null)
      this.setUser(null)
    },
    logout() {
      this.clearAuth()
    },
    async loadCurrentUser() {
      if (!this.token) throw new Error('missing token')
      const response = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${this.token}` },
      })
      const refreshed = response.headers.get('x-refresh-token')
      if (refreshed) this.setToken(refreshed)
      if (!response.ok) {
        const error: Error & { response?: { status: number } } = new Error('failed to load current user')
        error.response = { status: response.status }
        throw error
      }
      const data = await response.json()
      this.setUser(data || null)
      return this.user
    },
  },
})
