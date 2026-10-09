const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
let token = ''
let refreshPromise = null
export function setToken(value) { token = value || '' }

export async function refreshToken() {
  if (!refreshPromise) {
    refreshPromise = fetch(`${base}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async response => {
        if (!response.ok) { setToken(''); return false }
        setToken((await response.json()).access_token)
        return true
      }).catch(() => false).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

async function responseError(response) {
  const body = await response.json().catch(() => ({}))
  let message = body.error?.message || '请求失败，请稍后重试'
  if (Array.isArray(body.detail)) message = body.detail.map(x => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('；')
  const error = new Error(message)
  error.status = response.status
  error.code = body.error?.code
  return error
}

export async function request(path, options = {}, retry = true) {
  const response = await fetch(base + path, {
    ...options, credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
  })
  if (response.status === 401 && retry && !path.startsWith('/auth/') && await refreshToken()) return request(path, options, false)
  if (!response.ok) throw await responseError(response)
  return response
}

export async function api(path, method = 'GET', data) {
  const response = await request(path, { method, ...(data === undefined ? {} : { body: JSON.stringify(data) }) })
  return response.json()
}

export async function streamChat(data, signal, onEvent) {
  const response = await request('/chat/stream', { method: 'POST', body: JSON.stringify(data), signal })
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = block.split('\n')
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
        const payload = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
        if (event && payload) {
          const content = JSON.parse(payload)
          if (event === 'error') throw new Error(content.message || '生成失败')
          if (event === 'done') completed = true
          onEvent(event, content)
        }
      }
      if (done) break
    }
    if (!completed) throw new Error('连接中断，可通过运行记录确认结果')
  } finally { reader.releaseLock() }
}
