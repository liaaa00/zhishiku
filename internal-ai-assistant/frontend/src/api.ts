import axios from 'axios'
import { useAuthStore } from './stores/auth'

const http = axios.create({ baseURL: '/api' })
const REFRESH_WINDOW_SECONDS = 10 * 60
let refreshPromise: Promise<string | null> | null = null

function tokenExpiresInSeconds(token: string) {
  try {
    const payloadPart = token.split('.')[1]
    if (!payloadPart) return 0
    const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded))
    if (!payload?.exp) return 0
    return Number(payload.exp) - Math.floor(Date.now() / 1000)
  } catch {
    return 0
  }
}

function readToken() {
  return localStorage.getItem('token') || ''
}

function syncAuthPayload(data: any) {
  useAuthStore().setAuthPayload(data || {})
}

function clearAuthPayload() {
  useAuthStore().clearAuth()
}

async function refreshTokenIfNeeded(force = false) {
  const token = readToken()
  if (!token) return null
  if (!force && tokenExpiresInSeconds(token) > REFRESH_WINDOW_SECONDS) return token
  if (!refreshPromise) {
    refreshPromise = axios
      .post('/api/auth/refresh', null, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        syncAuthPayload(res.data)
        return res.data?.token || null
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

http.interceptors.request.use(async (config) => {
  const url = String(config.url || '')
  const skipRefresh = url.includes('/auth/login') || url.includes('/auth/refresh')
  const refreshed = skipRefresh ? null : await refreshTokenIfNeeded()
  const token = refreshed || readToken()
  if (token && !skipRefresh) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => {
    const refreshed = response.headers?.['x-refresh-token']
    if (refreshed) useAuthStore().setToken(refreshed)
    return response
  },
  async (error) => {
    const original = error.config || {}
    if (error.response?.status === 401 && !original.__retriedWithRefresh) {
      original.__retriedWithRefresh = true
      const refreshed = await refreshTokenIfNeeded(true)
      if (refreshed) {
        original.headers = { ...(original.headers || {}), Authorization: `Bearer ${refreshed}` }
        return http(original)
      }
    }

    if (error.response?.status === 401) {
      clearAuthPayload()

      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  },
)

export default http
