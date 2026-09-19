const JSON_HEADERS = { 'Content-Type': 'application/json' }

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status }
}

async function request(path, { method = 'GET', body, raw = false } = {}) {
  const init = { method, credentials: 'same-origin' }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) { init.headers = JSON_HEADERS; init.body = JSON.stringify(body) }

  const res = await fetch(path, init)
  if (raw) {
    if (!res.ok) throw new ApiError('فشل التحميل', res.status)
    return res
  }
  if (res.status === 204) return null

  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!res.ok) throw new ApiError(data?.detail || `خطأ ${res.status}`, res.status)
  return data
}

export const api = {
  // auth
  me:            () => request('/api/auth/me'),
  login:         (email, password) => request('/api/auth/login', { method: 'POST', body: { email, password } }),
  logout:        () => request('/api/auth/logout', { method: 'POST' }),
  updateMe:      (body) => request('/api/auth/me', { method: 'PATCH', body }),
  users:         () => request('/api/auth/users'),
  createUser:    (body) => request('/api/auth/users', { method: 'POST', body }),
  patchUser:     (id, body) => request(`/api/auth/users/${id}`, { method: 'PATCH', body }),
  deleteUser:    (id) => request(`/api/auth/users/${id}`, { method: 'DELETE' }),
  memberships:   (id) => request(`/api/auth/memberships/${id}`),
  grant:         (body) => request('/api/auth/memberships', { method: 'POST', body }),
  revoke:        (u, c) => request(`/api/auth/memberships?user_id=${u}&client_id=${c}`, { method: 'DELETE' }),

  // workspace
  clients:       () => request('/api/clients'),
  createClient:  (body) => request('/api/clients', { method: 'POST', body }),
  deleteClient:  (id) => request(`/api/clients/${id}`, { method: 'DELETE' }),
  brands:        (clientId) => request(`/api/brands${clientId ? `?client_id=${clientId}` : ''}`),
  createBrand:   (body) => request('/api/brands', { method: 'POST', body }),
  brand:         (id) => request(`/api/brands/${id}`),
  patchBrand:    (id, body) => request(`/api/brands/${id}`, { method: 'PATCH', body }),
  deleteBrand:   (id) => request(`/api/brands/${id}`, { method: 'DELETE' }),
  clearCore:     (id, key) => request(`/api/brands/${id}/core/${key}`, { method: 'DELETE' }),
  addChild:      (id, kind, body) => request(`/api/brands/${id}/${kind}`, { method: 'POST', body }),
  delChild:      (id, kind, itemId) => request(`/api/brands/${id}/${kind}/${itemId}`, { method: 'DELETE' }),
  bulkVoc:       (id, body) => request(`/api/brands/${id}/voc/bulk`, { method: 'POST', body }),

  // runs
  catalog:       () => request('/api/catalog'),
  createRun:     (body) => request('/api/runs', { method: 'POST', body }),
  regenSection:  (runId, key, model) => request(
                   `/api/runs/${runId}/sections/${key}${model ? `?model=${model}` : ''}`, { method: 'POST' }),
  runs:          (q = '') => request(`/api/runs${q}`),
  run:           (id) => request(`/api/runs/${id}`),
  deleteRun:     (id) => request(`/api/runs/${id}`, { method: 'DELETE' }),
  exportUrl:     (id, fmt) => `/api/runs/${id}/export?format=${fmt}`,

  uploadAsset:   (brandId, file, kind) => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    return request(`/api/brands/${brandId}/assets`, { method: 'POST', body: form })
  },

  // assist
  assistFields:  (body) => request('/api/assist/fields', { method: 'POST', body }),
  bootstrap:     (body) => request('/api/assist/bootstrap', { method: 'POST', body }),
  applyBootstrap:(body) => request('/api/assist/bootstrap/apply', { method: 'POST', body }),

  // tools
  economics:     (body) => request('/api/tools/unit-economics', { method: 'POST', body }),
  bundles:       (body) => request('/api/tools/bundles', { method: 'POST', body }),
  health:        () => request('/api/health'),
}

/**
 * Follow a run's SSE stream. Returns a cancel function.
 * Events: text | thinking | status | section | usage | done | error | end
 */
export function streamRun(runId, onEvent) {
  const source = new EventSource(`/api/runs/${runId}/stream`)
  source.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch { /* keep-alive comment */ }
  }
  source.onerror = () => { source.close(); onEvent({ type: 'end' }) }
  return () => source.close()
}
