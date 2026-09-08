const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const api = {
  health: () => fetch('/health').then((r) => r.json()),

  projects: {
    list: () => request('/projects'),
    create: (data) => request('/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id) => request(`/projects/${id}`),
  },

  models: {
    list: (kind) => request(`/models${kind ? `?kind=${kind}` : ''}`),
  },

  presets: {
    list: (kind) => request(`/presets${kind ? `?kind=${kind}` : ''}`),
    get: (id) => request(`/presets/${id}`),
  },

  engines: {
    list: () => request('/engines'),
  },

  loras: {
    list: (engine) => request(`/loras${engine ? `?engine=${engine}` : ''}`),
    create: (formData) => fetch(`${BASE}/loras`, { method: 'POST', body: formData }).then((r) => r.json()),
    update: (id, data) => request(`/loras/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    delete: (id) => request(`/loras/${id}`, { method: 'DELETE' }),
  },

  gallery: {
    list: (kind) => request(`/gallery${kind && kind !== 'all' ? `?kind=${kind}` : ''}`),
    favorite: (id, favorite) => request(`/gallery/${id}/favorite?favorite=${favorite}`, { method: 'PATCH' }),
    delete: (id) => request(`/gallery/${id}`, { method: 'DELETE' }),
  },

  jobs: {
    list: () => request('/jobs'),
    create: (data) => request('/jobs', { method: 'POST', body: JSON.stringify(data) }),
    get: (id) => request(`/jobs/${id}`),
    cancel: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  },

  config: {
    formats: () => request('/config/formats'),
    qualityPresets: () => request('/config/quality-presets'),
    steps: () => request('/config/steps'),
    controlVideo: () => request('/config/control-video'),
    advancedFields: () => request('/config/advanced-fields'),
    videoModes: () => request('/config/video-modes'),
    addons: () => request('/config/addons'),
    studio: (kind) => request(`/config/studio/${kind}`),
  },

  assets: {
    upload: (file, category, projectId) => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('category', category)
      if (projectId) fd.append('project_id', projectId)
      return fetch(`${BASE}/assets`, { method: 'POST', body: fd }).then((r) => r.json())
    },
    list: (category, search) => {
      const params = new URLSearchParams()
      if (category) params.set('category', category)
      if (search) params.set('search', search)
      const qs = params.toString()
      return request(`/assets${qs ? `?${qs}` : ''}`)
    },
    delete: (id) => request(`/assets/${id}`, { method: 'DELETE' }),
  },

  cloud: {
    providers: () => request('/cloud/providers'),
    getConnection: () => request('/cloud/connection'),
    saveConnection: (data) => request('/cloud/connection', { method: 'PUT', body: JSON.stringify(data) }),
    test: (data) => request('/cloud/test', { method: 'POST', body: JSON.stringify(data || {}) }),
  },
}
