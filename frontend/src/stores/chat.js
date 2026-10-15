import { defineStore } from 'pinia'
import { api, streamChat } from '../api'

let controller = null
export const useChat = defineStore('chat', {
  state: () => ({ sessions: [], currentId: null, messages: [], cursor: null, generating: false, stage: '', error: '', products: [], sources: [], recommendationId: null, requestId: null, webSearchEnabled: false, webSearchResult: null }),
  actions: {
    async loadSessions() { this.sessions = await api('/sessions') },
    async create() {
      if (this.generating) return
      const session = await api('/sessions', 'POST')
      await this.loadSessions()
      await this.select(session.id)
    },
    async select(id) {
      if (this.generating) return
      const result = await api(`/sessions/${id}/messages`)
      this.currentId = id; this.messages = result.items; this.cursor = result.next_cursor
      sessionStorage.setItem('current_session_id', id)
      this.products = []; this.sources = []; this.error = ''; this.recommendationId = null; this.requestId = null; this.webSearchResult = null
    },
    async older() {
      if (!this.cursor) return
      const result = await api(`/sessions/${this.currentId}/messages?before=${encodeURIComponent(this.cursor)}`)
      this.messages.unshift(...result.items); this.cursor = result.next_cursor
    },
    async edit(id, data) { await api(`/sessions/${id}`, 'PATCH', data); await this.loadSessions() },
    async remove(id) {
      await api(`/sessions/${id}`, 'DELETE'); await this.loadSessions()
      if (this.currentId === id) { this.currentId = null; this.messages = []; this.products = []; this.sources = []; this.recommendationId = null; this.webSearchResult = null; sessionStorage.removeItem('current_session_id') }
    },
    applyResult(result) {
      this.webSearchResult = result.web_search || null
      this.products = result.products || []; this.sources = result.sources || []; this.recommendationId = result.recommendation_id
      const last = this.messages.at(-1)
      if (last?.role === 'assistant') { last.content = result.answer; last.partial = false; last.timings = result.timings || null }
    },
    async send(message, savePreference = false) {
      if (this.generating || !message.trim()) return
      this.error = ''
      try {
        if (!this.currentId) await this.create()
        this.generating = true; this.stage = 'understanding'
        this.products = []; this.sources = []; this.recommendationId = null; this.webSearchResult = null
        this.requestId = crypto.randomUUID()
        this.messages.push({ id: this.requestId, role: 'user', content: message })
        this.messages.push({ id: `${this.requestId}-answer`, role: 'assistant', content: '', partial: true })
        controller = new AbortController()
        await streamChat({ session_id: this.currentId, request_id: this.requestId, message, save_preference: savePreference, web_search: this.webSearchEnabled }, controller.signal, (event, data) => {
          if (event === 'token') this.messages.at(-1).content += data.text
          if (event === 'reset') this.messages.at(-1).content = ''
          if (event === 'status') this.stage = data.stage
          if (event === 'web_search') this.webSearchResult = data
          if (event === 'timings') this.messages.at(-1).timings = data
          if (event === 'result') this.applyResult(data)
        })
      } catch (error) { this.error = error.name === 'AbortError' ? '已停止生成，当前内容未作为完整回答保存' : error.message }
      finally { this.generating = false; this.stage = ''; controller = null; await this.loadSessions().catch(() => {}) }
    },
    stop() { controller?.abort() },
    async recover() {
      if (!this.requestId) return
      const run = await api(`/runs/${this.requestId}`)
      if (run.status === 'succeeded') { this.applyResult(run.result); this.error = '' }
      else this.error = run.status === 'running' ? '服务端仍在处理，请稍后刷新结果' : `本轮未完成：${run.error_code}。可重新发送。`
    },
  },
})
