import { ENV } from '../config/env'

const JSON_CONTENT_TYPE = 'application/json'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const isFormData = (value) => typeof FormData !== 'undefined' && value instanceof FormData

const cleanQuery = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )

const appendCleanQuery = (query, params = {}) => {
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') {
          query.append(key, item)
        }
      })
      return
    }
    query.append(key, value)
  })
  return query
}

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

export const AUTH_STORAGE_KEY = 'sewpg.auth.session'
export const AUTH_EXPIRED_EVENT = 'sewpg.auth.expired'

const dispatchAuthExpired = (detail = {}) => {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(AUTH_STORAGE_KEY)
  window.dispatchEvent(
    new CustomEvent(AUTH_EXPIRED_EVENT, {
      detail: {
        message: '登录已过期，请重新登录。',
        ...detail,
      },
    }),
  )
}

const readAuthSession = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || typeof parsed.token !== 'string') return null
    if (Number.isFinite(parsed.expiresAt) && parsed.expiresAt <= Date.now()) {
      dispatchAuthExpired({ reason: 'expired' })
      return null
    }
    return parsed
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    return null
  }
}

const readAuthToken = () => readAuthSession()?.token || ''

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
    let requestAuthToken = ''
    try {
      const headers = new Headers(options.headers || {})
      if (ENV.API_ENABLE_TRACE) headers.set('x-trace-id', traceId)
      requestAuthToken = options.authToken ?? readAuthToken()
      if (requestAuthToken && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${requestAuthToken}`)
      }

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
        if (normalized.status === 401 && requestAuthToken && !options.skipAuthExpired) {
          dispatchAuthExpired({
            reason: 'unauthorized',
            message: normalized.message || '登录已过期，请重新登录。',
          })
        }
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

// ===== Business Gap Handling =====
export const businessGapsAPI = {
  list: (projectId) => request(`/business/projects/${projectId}/business-gaps`),
  run: (projectId) => request(`/business/projects/${projectId}/business-gaps/run`, { method: 'POST', timeoutMs: 10 * 60 * 1000, retryCount: 0 }),
  facts: (projectId) => request(`/business/projects/${projectId}/business-gaps/facts`),
  selectableMaterials: (projectId, params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/business/projects/${projectId}/business-gaps/selectable-materials${qs ? `?${qs}` : ''}`)
  },
  previewMaterial: (projectId, materialId, params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/business/projects/${projectId}/business-gaps/materials/${encodeURIComponent(materialId)}/preview${qs ? `?${qs}` : ''}`)
  },
  materialContentUrl: (projectId, materialId, fileName) =>
    joinUrl(
      ENV.API_BASE_URL,
      `/business/projects/${projectId}/business-gaps/materials/${encodeURIComponent(materialId)}/content/${encodeURIComponent(fileName || 'material.bin')}`,
    ),
  buildFacts: (projectId) =>
    request(`/business/projects/${projectId}/business-gaps/facts/build`, { method: 'POST' }),
  saveFacts: (projectId, data) =>
    request(`/business/projects/${projectId}/business-gaps/facts`, { method: 'PUT', body: data }),
  updateTask: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}`, { method: 'PATCH', body: data }),
  createManualTask: (projectId, tocNodeId, data) =>
    request(`/business/projects/${projectId}/business-gaps/toc/${tocNodeId}/manual-task`, { method: 'POST', body: data }),
  confirmArtifact: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/confirm-artifact`, { method: 'POST', body: data }),
  upload: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/upload`, { method: 'POST', body: data }),
  uploadFiles: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/upload-files`, {
      method: 'POST',
      body: data?.formData || data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  artifactContentUrl: (projectId, artifactId, fileName) =>
    joinUrl(
      ENV.API_BASE_URL,
      `/business/projects/${projectId}/business-gaps/artifacts/${encodeURIComponent(artifactId)}/content/${encodeURIComponent(fileName || 'artifact.docx')}`,
    ),
  removeArtifact: (projectId, taskId, artifactId) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/artifacts/${encodeURIComponent(artifactId)}`, { method: 'DELETE' }),
  selectMaterial: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/select-material`, { method: 'POST', body: data }),
  selectTemplate: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/select-template`, { method: 'POST', body: data }),
  aiDraft: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/ai-draft`, {
      method: 'POST',
      body: data,
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
  tableFill: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/table-fill`, {
      method: 'POST',
      body: data,
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
  syncArtifactMaterial: (projectId, taskId, data) =>
    request(`/business/projects/${projectId}/business-gaps/tasks/${taskId}/sync-artifact-material`, { method: 'POST', body: data }),
}

// ===== Technical workspace facades =====
export const technicalProjectsAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/technical/projects${qs ? `?${qs}` : ''}`)
  },
  get: (id) => request(`/technical/projects/${id}`),
  create: (data) => request('/technical/projects', { method: 'POST', body: data }),
  update: (id, data) => request(`/technical/projects/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/technical/projects/${id}`, { method: 'DELETE' }),
  materialsPath: (id) => request(`/technical/projects/${id}/materials-path`),
  templateFallback: (id) => request(`/technical/projects/${id}/template-fallback`),
  updateTemplateFallback: (id, data) =>
    request(`/technical/projects/${id}/template-fallback`, { method: 'PUT', body: data }),
  parseStatus: (id) => request(`/technical/projects/${id}/materials/parse-status`),
}

export const businessProjectInfoOptionsAPI = {
  get: () => request('/business/project-info/options'),
}

export const technicalProjectInfoOptionsAPI = {
  get: () => request('/technical/project-info/options'),
}

export const technicalStagesAPI = {
  list: (projectId) => request(`/technical/projects/${projectId}/stages`),
  update: (projectId, stage, data) =>
    request(`/technical/projects/${projectId}/stages/${stage}`, { method: 'PUT', body: data }),
}

export const technicalParseAPI = {
  results: (projectId) => request(`/technical/projects/${projectId}/parse-results`),
  progress: (projectId) => request(`/technical/projects/${projectId}/parse-results/progress`),
  cancel: (projectId) => request(`/technical/projects/${projectId}/parse-results/cancel`, { method: 'POST' }),
  run: (projectId) => request(`/technical/projects/${projectId}/parse-results/run`, { method: 'POST' }),
  uploadAndRun: (projectId, data) =>
    request(`/technical/projects/${projectId}/parse-results/upload-and-run`, {
      method: 'POST',
      body: data?.formData || data,
      signal: data?.signal,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  uploadTemplates: (projectId, data) =>
    request(`/technical/projects/${projectId}/template-files/upload`, {
      method: 'POST',
      body: data?.formData || data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  appendixPreview: (projectId, appendixId) =>
    request(`/technical/projects/${projectId}/parse-results/appendices/${encodeURIComponent(appendixId)}/preview`),
  approveAppendixAsset: (projectId, appendixId, data = {}) =>
    request(`/technical/projects/${projectId}/parse-results/appendices/${encodeURIComponent(appendixId)}/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  approveAllAppendixAssets: (projectId, data = {}) =>
    request(`/technical/projects/${projectId}/parse-results/appendices/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
}

export const technicalDirectoryAPI = {
  status: (projectId) => request(`/technical/projects/${projectId}/directory-generation`),
  run: (projectId) =>
    request(`/technical/projects/${projectId}/directory-generation/run`, {
      method: 'POST',
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  stream: (projectId, handlers = {}) =>
    createEventStream(`/technical/projects/${projectId}/directory-generation/stream`, handlers),
}

export const technicalOutlineAPI = {
  get: (projectId, params = {}) => {
    const qs = new URLSearchParams(cleanQuery({ fileId: params.fileId })).toString()
    return request(`/technical/projects/${projectId}/outline${qs ? `?${qs}` : ''}`)
  },
  save: (projectId, data) => request(`/technical/projects/${projectId}/outline`, { method: 'PUT', body: data }),
  regenerate: (projectId) => request(`/technical/projects/${projectId}/outline/regenerate`, { method: 'POST' }),
  confirm: (projectId) => request(`/technical/projects/${projectId}/outline/confirm`, { method: 'POST' }),
}

export const technicalGapsAPI = {
  detectionStatus: (projectId) => request(`/technical/projects/${projectId}/gaps-detection`),
  runDetection: (projectId) =>
    request(`/technical/projects/${projectId}/gaps-detection/run`, {
      method: 'POST',
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
  list: (projectId) => request(`/technical/projects/${projectId}/gaps`),
  update: (projectId, gid, data) =>
    request(`/technical/projects/${projectId}/gaps/${gid}`, { method: 'PUT', body: data }),
  upload: (projectId, gid, data) =>
    request(`/technical/projects/${projectId}/gaps/${gid}/upload`, { method: 'POST', body: data }),
  selectMaterial: (projectId, gid, data) =>
    request(`/technical/projects/${projectId}/gaps/${gid}/select-material`, { method: 'POST', body: data }),
  submitReview: (projectId) =>
    request(`/technical/projects/${projectId}/gaps/submit-review`, { method: 'POST' }),
  facts: (projectId) => request(`/technical/projects/${projectId}/gaps/facts`),
  buildFacts: (projectId) =>
    request(`/technical/projects/${projectId}/gaps/facts/build`, { method: 'POST' }),
  saveFacts: (projectId, data) =>
    request(`/technical/projects/${projectId}/gaps/facts`, { method: 'PUT', body: data }),
  recheck: (projectId) =>
    request(`/technical/projects/${projectId}/gaps/recheck`, { method: 'POST' }),
  aiFill: (projectId, gid, data) =>
    request(`/technical/projects/${projectId}/gaps/${gid}/ai-fill`, {
      method: 'POST',
      body: data,
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
  confirmAiFillArtifact: (projectId, gid, artifactId, data) =>
    request(`/technical/projects/${projectId}/gaps/${gid}/artifacts/${artifactId}/confirm`, {
      method: 'POST',
      body: data,
    }),
  aiFillAll: (projectId, data) =>
    request(`/technical/projects/${projectId}/gaps/ai-fill-all`, {
      method: 'POST',
      body: data,
      timeoutMs: 30 * 60 * 1000,
      retryCount: 0,
    }),
  submissions: (projectId) => request(`/technical/projects/${projectId}/materials/submissions`),
  submitMaterial: (projectId, data) =>
    request(`/technical/projects/${projectId}/materials/submissions`, { method: 'POST', body: data }),
  updateMissing: (projectId, missingId, data) =>
    request(`/technical/projects/${projectId}/materials/missing/${missingId}`, { method: 'PATCH', body: data }),
}

export const technicalGenerateAPI = {
  status: (projectId) => request(`/technical/projects/${projectId}/fill-generation`),
  run: (projectId) =>
    request(`/technical/projects/${projectId}/fill-generation/run`, {
      method: 'POST',
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
}

export const technicalDocumentAPI = {
  get: (projectId) => request(`/technical/projects/${projectId}/document`),
  save: (projectId, data) =>
    request(`/technical/projects/${projectId}/document/save`, { method: 'PUT', body: data }),
  forceSave: (projectId) =>
    request(`/technical/projects/${projectId}/document/force-save`, { method: 'POST' }),
  technicalFormat: (projectId, data) =>
    request(`/technical/projects/${projectId}/document/technical-format`, { method: 'POST', body: data, timeoutMs: 5 * 60 * 1000 }),
  final: (projectId) => request(`/technical/projects/${projectId}/final-document`),
  finalPdf: (projectId) => request(`/technical/projects/${projectId}/final-document/pdf`, { timeoutMs: 5 * 60 * 1000, retryCount: 0 }),
}

export const technicalMaterialsAPI = {
  identityOptions: () => request('/technical/materials/identity-options'),
  turbineModelOptions: () => request('/technical/materials/turbine-model-options'),
  index: () => request('/technical/materials/index'),
  setIndexTags: (data) => request('/technical/materials/index/tags', { method: 'PUT', body: data }),
  raw: {
    tree: () => request('/technical/materials/raw/tree'),
    files: (params = {}) => {
      const qs = appendCleanQuery(new URLSearchParams(), params).toString()
      return request(`/technical/materials/raw/files${qs ? `?${qs}` : ''}`)
    },
    upload: (data) =>
      request('/technical/materials/raw/upload', { method: 'POST', body: data, timeoutMs: 30 * 60 * 1000 }),
    bootstrapFolders: (data) =>
      request('/technical/materials/raw/folders/bootstrap', { method: 'POST', body: data }),
    createFolder: (data) =>
      request('/technical/materials/raw/folders', { method: 'POST', body: data }),
    moveFolder: (data) =>
      request('/technical/materials/raw/folders/move', { method: 'POST', body: data }),
    deleteFolder: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/technical/materials/raw/folders${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    updateFile: (id, data) => request(`/technical/materials/raw/${id}`, { method: 'PATCH', body: data }),
    tagImportPreview: (data) =>
      request('/technical/materials/raw/tag-import/preview', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    tagImportCommit: (data) =>
      request('/technical/materials/raw/tag-import/commit', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    moveFile: (data) => request('/technical/materials/raw/move', { method: 'POST', body: data }),
    deleteFile: (id) => request(`/technical/materials/raw/${id}`, { method: 'DELETE' }),
    batchDelete: (data) => request('/technical/materials/raw/batch-delete', { method: 'POST', body: data }),
    batchTags: (data) => request('/technical/materials/raw/batch-tags', { method: 'POST', body: data }),
    batchCertificateTime: (data) =>
      request('/technical/materials/raw/certificate-time/batch', { method: 'POST', body: data, timeoutMs: 20 * 60 * 1000 }),
    previewTechnicalSplit: (id, data) =>
      request(`/technical/materials/raw/${id}/split/preview`, { method: 'POST', body: data, timeoutMs: 5 * 60 * 1000 }),
    confirmTechnicalSplit: (id, data) =>
      request(`/technical/materials/raw/${id}/split/confirm`, { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    previewCleanedFile: (id) => request(`/technical/materials/raw/${id}/cleaned/preview`),
    contentUrl: (id) => joinUrl(ENV.API_BASE_URL, `/technical/materials/raw/${id}/content`),
    previewContentUrl: (id) => joinUrl(ENV.API_BASE_URL, `/technical/materials/raw/${id}/preview-content`),
    cleanedContentUrl: (id, fileName) =>
      joinUrl(ENV.API_BASE_URL, `/technical/materials/raw/${id}/cleaned/content/${encodeURIComponent(fileName || 'cleaned.docx')}`),
    parseStatus: (projectId) => request(`/technical/projects/${projectId}/materials/parse-status`),
  },
  wiki: {
    list: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/technical/materials/wiki${qs ? `?${qs}` : ''}`)
    },
    bootstrap: (data = {}) =>
      request('/technical/materials/wiki/bootstrap', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    create: (data) => request('/technical/materials/wiki', { method: 'POST', body: data }),
    update: (id, data) => request(`/technical/materials/wiki/${id}`, { method: 'PUT', body: data }),
    delete: (id, params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/technical/materials/wiki/${id}${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    move: (id, data) => request(`/technical/materials/wiki/${id}/move`, { method: 'POST', body: data }),
    uploadAttachment: (id, data) =>
      request(`/technical/materials/wiki/${id}/attachments`, { method: 'POST', body: data }),
    deleteAttachment: (id, params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/technical/materials/wiki/attachments/${id}${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    refreshSummary: (id, data = {}) =>
      request(`/technical/materials/wiki/${id}/refresh-summary`, { method: 'POST', body: data }),
    certificateTime: () => request('/technical/materials/wiki/certificate-time'),
    updateCertificateTime: (fileId, data) =>
      request(`/technical/materials/wiki/certificate-time/${fileId}`, { method: 'PATCH', body: data }),
  },
  certificates: {
    ledger: () => request('/technical/materials/certificates'),
    suggestions: () => request('/technical/materials/certificates/suggestions'),
    saveScopes: (data) => request('/technical/materials/certificates/scopes', { method: 'PUT', body: data }),
    incremental: (data = {}) =>
      request('/technical/materials/certificates/incremental', { method: 'POST', body: data, timeoutMs: 20 * 60 * 1000 }),
    recognize: (fileId) =>
      request(`/technical/materials/certificates/${fileId}/recognize`, { method: 'POST', timeoutMs: 10 * 60 * 1000 }),
    update: (fileId, data) =>
      request(`/technical/materials/certificates/${fileId}`, { method: 'PATCH', body: data }),
    delete: (fileId) => request(`/technical/materials/certificates/${fileId}`, { method: 'DELETE' }),
    bulkDelete: (fileIds = []) =>
      request('/technical/materials/certificates/bulk-delete', { method: 'POST', body: { fileIds } }),
  },
}

export const technicalAuditAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/technical/audit${qs ? `?${qs}` : ''}`)
  },
  detail: (id) => request(`/technical/audit/${id}`),
  exportCsv: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/technical/audit/export${qs ? `?${qs}` : ''}`)
  },
}

// ===== Business workspace facades =====
export const businessProjectsAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/business/projects${qs ? `?${qs}` : ''}`)
  },
  get: (id) => request(`/business/projects/${id}`),
  create: (data) => request('/business/projects', { method: 'POST', body: data }),
  update: (id, data) => request(`/business/projects/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/business/projects/${id}`, { method: 'DELETE' }),
  templateFallback: (id) => request(`/business/projects/${id}/template-fallback`),
  updateTemplateFallback: (id, data) =>
    request(`/business/projects/${id}/template-fallback`, { method: 'PUT', body: data }),
}

export const businessStagesAPI = {
  list: (projectId) => request(`/business/projects/${projectId}/stages`),
  update: (projectId, stage, data) =>
    request(`/business/projects/${projectId}/stages/${stage}`, { method: 'PUT', body: data }),
}

export const businessParseAPI = {
  results: (projectId) => request(`/business/projects/${projectId}/parse-results`),
  progress: (projectId) => request(`/business/projects/${projectId}/parse-results/progress`),
  cancel: (projectId) => request(`/business/projects/${projectId}/parse-results/cancel`, { method: 'POST' }),
  appendixPreview: (projectId, appendixId) =>
    request(`/business/projects/${projectId}/parse-results/appendices/${encodeURIComponent(appendixId)}/preview`),
  approveAppendixAsset: (projectId, appendixId, data = {}) =>
    request(`/business/projects/${projectId}/parse-results/appendices/${encodeURIComponent(appendixId)}/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  approveAllAppendixAssets: (projectId, data = {}) =>
    request(`/business/projects/${projectId}/parse-results/appendices/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  approveBusinessScoringAsset: (projectId, data = {}) =>
    request(`/business/projects/${projectId}/parse-results/business-scoring/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  commitmentLetterPreview: (projectId, letterId) =>
    request(`/business/projects/${projectId}/parse-results/commitment-letters/${encodeURIComponent(letterId)}/preview`),
  approveCommitmentLetterAsset: (projectId, letterId, data = {}) =>
    request(`/business/projects/${projectId}/parse-results/commitment-letters/${encodeURIComponent(letterId)}/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  approveAllCommitmentLetterAssets: (projectId, data = {}) =>
    request(`/business/projects/${projectId}/parse-results/commitment-letters/approve`, {
      method: 'POST',
      body: data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  uploadAndRun: (projectId, data) =>
    request(`/business/projects/${projectId}/parse-results/upload-and-run`, {
      method: 'POST',
      body: data?.formData || data,
      signal: data?.signal,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
  uploadTemplates: (projectId, data) =>
    request(`/business/projects/${projectId}/template-files/upload`, {
      method: 'POST',
      body: data?.formData || data,
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
}

export const businessDirectoryAPI = {
  status: (projectId) => request(`/business/projects/${projectId}/directory-generation`),
  run: (projectId) =>
    request(`/business/projects/${projectId}/directory-generation/run`, {
      method: 'POST',
      timeoutMs: 5 * 60 * 1000,
      retryCount: 0,
    }),
}

export const businessOutlineAPI = {
  get: (projectId, params = {}) => {
    const qs = new URLSearchParams(cleanQuery({ fileId: params.fileId })).toString()
    return request(`/business/projects/${projectId}/outline${qs ? `?${qs}` : ''}`)
  },
  save: (projectId, data) => request(`/business/projects/${projectId}/outline`, { method: 'PUT', body: data }),
  confirm: (projectId) => request(`/business/projects/${projectId}/outline/confirm`, { method: 'POST' }),
}

export const businessGenerateAPI = {
  status: (projectId) => request(`/business/projects/${projectId}/fill-generation`),
  run: (projectId) =>
    request(`/business/projects/${projectId}/fill-generation/run`, {
      method: 'POST',
      timeoutMs: 10 * 60 * 1000,
      retryCount: 0,
    }),
}

export const businessDocumentAPI = {
  get: (projectId) => request(`/business/projects/${projectId}/document`),
  save: (projectId, data) =>
    request(`/business/projects/${projectId}/document/save`, { method: 'PUT', body: data }),
  businessChat: (projectId, data) =>
    request(`/business/projects/${projectId}/document/business-chat`, { method: 'POST', body: data, timeoutMs: 2 * 60 * 1000 }),
  businessRewriteSuggest: (projectId, data) =>
    request(`/business/projects/${projectId}/document/business-rewrite/suggest`, { method: 'POST', body: data, timeoutMs: 2 * 60 * 1000 }),
  businessRewriteApply: (projectId, data) =>
    request(`/business/projects/${projectId}/document/business-rewrite/apply`, { method: 'POST', body: data, timeoutMs: 2 * 60 * 1000 }),
  businessFormat: (projectId, data) =>
    request(`/business/projects/${projectId}/document/business-format`, { method: 'POST', body: data, timeoutMs: 5 * 60 * 1000 }),
  final: (projectId) => request(`/business/projects/${projectId}/final-document`),
  finalPdf: (projectId) => request(`/business/projects/${projectId}/final-document/pdf`, { timeoutMs: 5 * 60 * 1000, retryCount: 0 }),
}

// 业绩库（业绩 / Performance）为商务标、技术标共享的公共模块，使用中性路径 /materials/performance
export const performanceAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/materials/performance${qs ? `?${qs}` : ''}`)
  },
  categories: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/materials/performance/categories${qs ? `?${qs}` : ''}`)
  },
  previewCategory: (data) =>
    request('/materials/performance/categories/preview', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
  importCategory: (data) =>
    request('/materials/performance/categories/import', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
  category: (id) => request(`/materials/performance/categories/${id}`),
  deleteCategory: (id, data = {}) => request(`/materials/performance/categories/${id}`, { method: 'DELETE', body: data }),
  updateCategoryStatus: (id, data) => request(`/materials/performance/categories/${id}/status`, { method: 'PATCH', body: data }),
  uploadCategoryAttachment: (id, data) =>
    request(`/materials/performance/categories/${id}/attachments`, { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
  previewCategoryAttachment: (categoryId, attachmentId) =>
    request(`/materials/performance/categories/${categoryId}/attachments/${attachmentId}/preview`),
  categoryAttachmentUrl: (categoryId, attachmentId) =>
    joinUrl(ENV.API_BASE_URL, `/materials/performance/categories/${categoryId}/attachments/${attachmentId}`),
  previewItemAttachment: (categoryId, itemId, attachmentId) =>
    request(`/materials/performance/categories/${categoryId}/items/${itemId}/attachments/${attachmentId}/preview`),
  itemAttachmentUrl: (categoryId, itemId, attachmentId) =>
    joinUrl(ENV.API_BASE_URL, `/materials/performance/categories/${categoryId}/items/${itemId}/attachments/${attachmentId}`),
  create: (data) => request('/materials/performance', { method: 'POST', body: data }),
  update: (id, data) => request(`/materials/performance/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/materials/performance/${id}`, { method: 'DELETE' }),
  uploadWord: (id, data) =>
    request(`/materials/performance/${id}/word`, { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
  wordUrl: (id) => joinUrl(ENV.API_BASE_URL, `/materials/performance/${id}/word`),
}

export const businessMaterialsAPI = {
  identityOptions: () => request('/business/materials/identity-options'),
  raw: {
    tree: () => request('/business/materials/raw/tree'),
    files: (params = {}) => {
      const qs = appendCleanQuery(new URLSearchParams(), params).toString()
      return request(`/business/materials/raw/files${qs ? `?${qs}` : ''}`)
    },
    upload: (data) =>
      request('/business/materials/raw/upload', { method: 'POST', body: data, timeoutMs: 30 * 60 * 1000 }),
    createFolder: (data) =>
      request('/business/materials/raw/folders', { method: 'POST', body: data }),
    moveFolder: (data) =>
      request('/business/materials/raw/folders/move', { method: 'POST', body: data }),
    deleteFolder: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/business/materials/raw/folders${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    updateFile: (id, data) => request(`/business/materials/raw/${id}`, { method: 'PATCH', body: data }),
    moveFile: (data) => request('/business/materials/raw/move', { method: 'POST', body: data }),
    deleteFile: (id) => request(`/business/materials/raw/${id}`, { method: 'DELETE' }),
    previewBusinessSplit: (id, data) =>
      request(`/business/materials/raw/${id}/business-split/preview`, { method: 'POST', body: data, timeoutMs: 5 * 60 * 1000 }),
    confirmBusinessSplit: (id, data) =>
      request(`/business/materials/raw/${id}/business-split/confirm`, { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    previewCleanedFile: (id) => request(`/business/materials/raw/${id}/cleaned/preview`),
    contentUrl: (id) => joinUrl(ENV.API_BASE_URL, `/business/materials/raw/${id}/content`),
    cleanedContentUrl: (id, fileName) =>
      joinUrl(ENV.API_BASE_URL, `/business/materials/raw/${id}/cleaned/content/${encodeURIComponent(fileName || 'cleaned.docx')}`),
    parseStatus: (projectId) => request(`/business/projects/${projectId}/materials/parse-status`),
  },
  wiki: {
    list: (params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/business/materials/wiki${qs ? `?${qs}` : ''}`)
    },
    bootstrap: (data = {}) =>
      request('/business/materials/wiki/bootstrap', { method: 'POST', body: data, timeoutMs: 10 * 60 * 1000 }),
    create: (data) => request('/business/materials/wiki', { method: 'POST', body: data }),
    update: (id, data) => request(`/business/materials/wiki/${id}`, { method: 'PUT', body: data }),
    delete: (id, params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/business/materials/wiki/${id}${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    move: (id, data) => request(`/business/materials/wiki/${id}/move`, { method: 'POST', body: data }),
    uploadAttachment: (id, data) =>
      request(`/business/materials/wiki/${id}/attachments`, { method: 'POST', body: data }),
    deleteAttachment: (id, params = {}) => {
      const qs = new URLSearchParams(cleanQuery(params)).toString()
      return request(`/business/materials/wiki/attachments/${id}${qs ? `?${qs}` : ''}`, { method: 'DELETE' })
    },
    refreshSummary: (id, data = {}) =>
      request(`/business/materials/wiki/${id}/refresh-summary`, { method: 'POST', body: data }),
  },
}

export const businessAuditAPI = {
  list: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/business/audit${qs ? `?${qs}` : ''}`)
  },
  detail: (id) => request(`/business/audit/${id}`),
  exportCsv: (params = {}) => {
    const qs = new URLSearchParams(cleanQuery(params)).toString()
    return request(`/business/audit/export${qs ? `?${qs}` : ''}`)
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
    test: (data) => request('/settings/llm-gateway/test', { method: 'POST', body: data, timeoutMs: 90 * 1000 }),
  },
  ocr: {
    get: () => request('/settings/ocr'),
    update: (data) => request('/settings/ocr', { method: 'PUT', body: data }),
    test: (data) => request('/settings/ocr/test', { method: 'POST', body: data, timeoutMs: 90 * 1000 }),
  },
  defaultTemplates: {
    list: () => request('/settings/default-templates'),
    upload: (data) => request('/settings/default-templates', { method: 'POST', body: data }),
    activate: (id) => request(`/settings/default-templates/${id}/activate`, { method: 'POST' }),
  },
  health: () => request('/settings/health'),
}

// ===== Auth =====
export const authAPI = {
  login: (data) => request('/auth/login', { method: 'POST', body: data, skipAuthExpired: true }),
  me: (token) => request('/auth/me', { authToken: token, skipAuthExpired: true }),
  logout: () => request('/auth/logout', { method: 'POST', skipAuthExpired: true }),
}

// ===== Dashboard =====
export const dashboardAPI = {
  get: () => request('/dashboard'),
}

export { ApiError }
