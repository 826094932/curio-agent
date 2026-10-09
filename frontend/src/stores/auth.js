import { defineStore } from 'pinia'
import { api, setToken, refreshToken } from '../api'

export const useAuth = defineStore('auth', {
  state: () => ({ user: null, initialized: false }),
  actions: {
    async restore() {
      if (this.initialized) return
      try { if (await refreshToken()) this.user = await api('/users/me') }
      finally { this.initialized = true }
    },
    async login(email, password) {
      const result = await api('/auth/login', 'POST', { email, password })
      setToken(result.access_token)
      this.user = await api('/users/me')
      this.initialized = true
    },
    async logout() {
      try { await api('/auth/logout', 'POST') }
      finally { setToken(''); this.user = null; this.initialized = true; sessionStorage.removeItem('current_session_id') }
    },
  },
})
