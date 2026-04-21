import { ENV } from '../config/env'

const JSON_CONTENT_TYPE = 'application/json'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const isFormData = (value) => typeof FormData !== 'undefined' && value instanceof FormData

const cleanQuery = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )

const joinUrl = (base, path) => {
  if (base.startsWith('http://') || base.startsWith('https://')) {
    return `${base.replace(/\/+$/, '')}${path}`
  }
  return `${base || ''}${path}`
}

const createEventStream = (path, handlers = {}) => {
  const source = new EventSource(joinUrl(ENV.API_BASE_URL, path))
  const onState = handlers.onState
  const onError = handlers.onError

  source.onmessage = (event) => {
    if (!onState) return
    try {
      onState(JSON.parse(event.data))
    } catch (error) {
      onError?.(error)
    }
  }
  source.onerror = (error) => {
    onError?.(error)
  }

  return source
}

const createTraceId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const random = Math.random().toString(36).slice(2, 10)
  return `trace-${Date.now()}-${random}`
}

const parseResponseBody = async (response) => {
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes(JSON_CONTENT_TYPE)) return response.json()
  return response.text()
}

const getErrorMessage = (payload, fallback) => {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  return payload.detail || payload.message || payload.error || fallback
}

const getErrorCode = (payload, status) => {
  if (payload && typeof payload === 'object' && payload.code) return payload.code
  return `HTTP_${status}`
}

class ApiError extends Error {
  constructor(message, options = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status || 0
    this.code = options.code || 'API_ERROR'
    this.traceId = options.traceId || null
    this.url = options.url || ''
    this.payload = options.payload || null
  }
}

const shouldRetry = (error, method, attempt, maxRetries) => {
  if (attempt >= maxRetries) return false
  if (method !== 'GET') return false
  if (!(error instanceof ApiError)) return true
  if (error.code === 'TIMEOUT' || error.code === 'NETWORK_ERROR') return true
  return error.status >= 500
}

const createController = (timeoutMs, signal) => {
  const controller = new AbortController()
  let didTimeout = false

  const timeoutId = setTimeout(() => {
    didTimeout = true
    controller.abort()
  }, timeoutMs)

  const onAbort = () => controller.abort()
  if (signal) {
    if (signal.aborted) {
      onAbort()
    } else {
      signal.addEventListener('abort', onAbort, { once: true })
    }
  }

  return {
    controller,
    didTimeout: () => didTimeout,
    cleanup: () => {
      clearTimeout(timeoutId)
      if (signal) signal.removeEventListener('abort', onAbort)
    },
  }
}

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const timeoutMs = options.timeoutMs ?? ENV.API_TIMEOUT_MS
  const maxRetries =
    options.retryCount ?? (method === 'GET' ? Math.max(0, ENV.API_RETRY_COUNT) : 0)
  const traceId = options.traceId || createTraceId()
  const requestUrl = joinUrl(ENV.API_BASE_URL, path)

  let attempt = 0

  while (attempt <= maxRetries) {
    const { controller, didTimeout, cleanup } = createController(timeoutMs, options.signal)
    try {
      const headers = new Headers(options.headers || {})
      if (ENV.API_ENABLE_TRACE) headers.set('x-trace-id', traceId)

      const hasBody = options.body !== undefined && options.body !== null
      let body = options.body
      if (hasBody && typeof body === 'object' && !isFormData(body)) {
        if (!headers.has('Content-Type')) headers.set('Content-Type', JSON_CONTENT_TYPE)
        body = JSON.stringify(body)
      }

      const response = await fetch(requestUrl, {
        method,
        body,
        headers,
        signal: controller.signal,
      })

      const payload = await parseResponseBody(response)
      if (!response.ok) {
        const message = getErrorMessage(payload, response.statusText || 'Request failed')
        const code = getErrorCode(payload, response.status)
        throw new ApiError(message, {
          status: response.status,
          code,
          traceId: response.headers.get('x-trace-id') || traceId,
          url: requestUrl,
          payload,
        })
      }

      return payload
    } catch (error) {
      let normalized = error

      if (error?.name === 'AbortError') {
        normalized = new ApiError(
          didTimeout() ? '请求超时，请稍后重试。' : '请求已取消。',
          {
            status: 0,
            code: didTimeout() ? 'TIMEOUT' : 'ABORTED',
            traceId,
            url: requestUrl,
          },
        )
      } else if (!(error instanceof ApiError)) {
        normalized = new ApiError(error?.message || '网络异常，请检查连接。', {
          status: 0,
          code: 'NETWORK_ERROR',
          traceId,
          url: requestUrl,
        })
      }

      if (!shouldRetry(normalized, method, attempt, maxRetries)) {
        throw normalized
      }

      const backoff = 200 * 2 ** attempt + Math.floor(Math.random() * 150)
      await sleep(backoff)
      attempt += 1
    } finally {
      cleanup()
    }
  }

  throw new ApiError('请求失败，请稍后重试。', {
    status: 0,
    code: 'UNKNOWN',
    traceId,
    url: requestUrl,
  })
}

// ===== Projects =====
export const projectsAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/projects${qs ? `?${qs}` : ''}`)
  },
  get: (id) => request(`/projects/${id}`),
  create: (data) => request('/projects', { method: 'POST', body: data }),
  update: (id, data) => request(`/projects/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/projects/${id}`, { method: 'DELETE' }),
  cockpit: (id) => request(`/projects/${id}/cockpit`),
  materialsPath: (id) => request(`/projects/${id}/materials-path`),
  parseStatus: (id) => request(`/projects/${id}/materials/parse-status`),
}

// ===== Customers =====
export const customersAPI = {
  keyAccounts: () => request('/customers/key-accounts'),
}

// ===== Stages =====
export const stagesAPI = {
  list: (projectId) => request(`/projects/${projectId}/stages`),
  update: (projectId, stage, data) =>
    request(`/projects/${projectId}/stages/${stage}`, { method: 'PUT', body: data }),
}

// ===== S1 Parse =====
export const parseAPI = {
  results: (projectId) => request(`/projects/${projectId}/parse-results`),
  run: (projectId) => request(`/projects/${projectId}/parse-results/run`, { method: 'POST' }),
  uploadAndRun: (projectId, data) =>
    request(`/projects/${projectId}/parse-results/upload-and-run`, {
      method: 'POST',
      body: data?.formData || data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  updateItem: (projectId, rid, data) =>
    request(`/projects/${projectId}/parse-results/${rid}`, { method: 'PUT', body: data }),
}

// ===== S2 Directory Generate =====
export const directoryAPI = {
  status: (projectId) => request(`/projects/${projectId}/directory-generation`),
  run: (projectId) =>
    request(`/projects/${projectId}/directory-generation/run`, {
      method: 'POST',
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  stream: (projectId, handlers = {}) =>
    createEventStream(`/projects/${projectId}/directory-generation/stream`, handlers),
}

// ===== S3 Outline =====
export const outlineAPI = {
  get: (projectId) => request(`/projects/${projectId}/outline`),
  save: (projectId, data) => request(`/projects/${projectId}/outline`, { method: 'PUT', body: data }),
  regenerate: (projectId) => request(`/projects/${projectId}/outline/regenerate`, { method: 'POST' }),
  confirm: (projectId) => request(`/projects/${projectId}/outline/confirm`, { method: 'POST' }),
}

// ===== S4/S5 Gaps =====
export const gapsAPI = {
  detectionStatus: (projectId) => request(`/projects/${projectId}/gaps-detection`),
  runDetection: (projectId) => request(`/projects/${projectId}/gaps-detection/run`, { method: 'POST' }),
  list: (projectId) => request(`/projects/${projectId}/gaps`),
  update: (projectId, gid, data) =>
    request(`/projects/${projectId}/gaps/${gid}`, { method: 'PUT', body: data }),
  upload: (projectId, gid, data) =>
    request(`/projects/${projectId}/gaps/${gid}/upload`, { method: 'POST', body: data }),
  submitReview: (projectId) =>
    request(`/projects/${projectId}/gaps/submit-review`, { method: 'POST' }),
  submissions: (projectId) => request(`/projects/${projectId}/materials/submissions`),
  submitMaterial: (projectId, data) =>
    request(`/projects/${projectId}/materials/submissions`, { method: 'POST', body: data }),
  updateMissing: (projectId, missingId, data) =>
    request(`/projects/${projectId}/materials/missing/${missingId}`, { method: 'PATCH', body: data }),
}

// ===== S6 Review =====
export const reviewAPI = {
  list: (projectId) => request(`/projects/${projectId}/review-items`),
  prepareParse: (projectId) =>
    request(`/projects/${projectId}/review-items/prepare`, { method: 'POST' }),
  document: (projectId) => request(`/projects/${projectId}/review-items/document`),
  saveDocument: (projectId, data) =>
    request(`/projects/${projectId}/review-items/document/save`, { method: 'PUT', body: data }),
  forceSaveDocument: (projectId) =>
    request(`/projects/${projectId}/review-items/document/force-save`, { method: 'POST' }),
  confirm: (projectId) =>
    request(`/projects/${projectId}/review-items/confirm`, { method: 'POST' }),
}

// ===== S7 Generate =====
export const generateAPI = {
  status: (projectId) => request(`/projects/${projectId}/fill-generation`),
  run: (projectId) =>
    request(`/projects/${projectId}/fill-generation/run`, {
      method: 'POST',
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
}

// ===== S8 Coverage =====
export const coverageAPI = {
  get: (projectId) => request(`/projects/${projectId}/coverage`),
}

// ===== S9 Document =====
export const documentAPI = {
  get: (projectId) => request(`/projects/${projectId}/document`),
  save: (projectId, data) =>
    request(`/projects/${projectId}/document/save`, { method: 'PUT', body: data }),
  forceSave: (projectId) =>
    request(`/projects/${projectId}/document/force-save`, { method: 'POST' }),
  final: (projectId) => request(`/projects/${projectId}/final-document`),
}

// ===== S10 Export =====
export const exportAPI = {
  check: (projectId) => request(`/projects/${projectId}/export/check`),
  doExport: (projectId, data) => request(`/projects/${projectId}/export`, { method: 'POST', body: data }),
}

// ===== Materials =====
export const materialsAPI = {
  raw: {
    permissions: () => request('/materials/raw/permissions'),
    tree: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/raw/tree${qs ? `?${qs}` : ''}`)
    },
    files: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/raw/files${qs ? `?${qs}` : ''}`)
    },
    upload: (data) => request('/materials/raw/upload', { method: 'POST', body: data }),
    bootstrapFolders: (data) =>
      request('/materials/raw/folders/bootstrap', { method: 'POST', body: data }),
    createFolder: (data) =>
      request('/materials/raw/folders', { method: 'POST', body: data }),
    deleteFolder: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/raw/folders${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    updateFile: (id, data) => request(`/materials/raw/${id}`, { method: 'PATCH', body: data }),
    moveFile: (data) => request('/materials/raw/move', { method: 'POST', body: data }),
    deleteFile: (id) => request(`/materials/raw/${id}`, { method: 'DELETE' }),
    downloadFile: (id) => request(`/materials/raw/${id}/download`),
    parseStatus: (projectId) => request(`/projects/${projectId}/materials/parse-status`),
  },
  structured: {
    list: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/structured${qs ? `?${qs}` : ''}`)
    },
    downloadTemplate: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/structured/template${qs ? `?${qs}` : ''}`)
    },
    previewImport: (data) =>
      request('/materials/structured/import/preview', { method: 'POST', body: data }),
    confirmImport: (data) =>
      request('/materials/structured/import/confirm', { method: 'POST', body: data }),
    create: (data) => request('/materials/structured', { method: 'POST', body: data }),
    update: (id, data) => request(`/materials/structured/${id}`, { method: 'PUT', body: data }),
    delete: (id) => request(`/materials/structured/${id}`, { method: 'DELETE' }),
    importExcel: (formData) =>
      request('/materials/structured/import', { method: 'POST', body: formData }),
  },
  wiki: {
    list: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/materials/wiki${qs ? `?${qs}` : ''}`)
    },
    create: (data) => request('/materials/wiki', { method: 'POST', body: data }),
    update: (id, data) => request(`/materials/wiki/${id}`, { method: 'PUT', body: data }),
    move: (id, data) => request(`/materials/wiki/${id}/move`, { method: 'POST', body: data }),
    uploadAttachment: (id, data) =>
      request(`/materials/wiki/${id}/attachments`, { method: 'POST', body: data }),
    refreshSummary: (id) => request(`/materials/wiki/${id}/refresh-summary`, { method: 'POST' }),
  },
}

// ===== Audit =====
export const auditAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/audit${qs ? `?${qs}` : ''}`)
  },
  detail: (id) => request(`/audit/${id}`),
  exportCsv: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/audit/export${qs ? `?${qs}` : ''}`)
  },
}

// ===== Settings =====
export const settingsAPI = {
  users: {
    list: () => request('/settings/users'),
    create: (data) => request('/settings/users', { method: 'POST', body: data }),
    update: (id, data) => request(`/settings/users/${id}`, { method: 'PUT', body: data }),
  },
  gateway: {
    get: () => request('/settings/llm-gateway'),
    update: (data) => request('/settings/llm-gateway', { method: 'PUT', body: data }),
    test: (data) => request('/settings/llm-gateway/test', { method: 'POST', body: data }),
  },
  dotxTemplates: {
    list: () => request('/settings/dotx-templates'),
    upload: (data) => request('/settings/dotx-templates', { method: 'POST', body: data }),
    activate: (id) => request(`/settings/dotx-templates/${id}/activate`, { method: 'POST' }),
  },
  excelTemplates: {
    list: () => request('/settings/excel-templates'),
    upload: (data) => request('/settings/excel-templates', { method: 'POST', body: data }),
    activate: (id) => request(`/settings/excel-templates/${id}/activate`, { method: 'POST' }),
  },
  backups: {
    list: () => request('/settings/backups'),
    create: (data = {}) => request('/settings/backups/create', { method: 'POST', body: data }),
    restore: (id) => request(`/settings/backups/${id}/restore`, { method: 'POST' }),
  },
  health: () => request('/settings/health'),
}

// ===== Auth =====
export const authAPI = {
  login: (data) => request('/auth/login', { method: 'POST', body: data }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
}

export { ApiError }
