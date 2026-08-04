// 用户行为埋点采集器：采集 click / route / api / error 四类事件，批量上报到 /api/<线>/events
// 上报刻意不走 src/api/index.js 的 request()，避免埋点请求自身被递归采集；
// 所有采集逻辑只做旁观记录，任何异常都吞掉（最多 console.warn 一次），绝不影响业务
import { ENV } from '../config/env'
import { AUTH_STORAGE_KEY, onApiEvent } from '../api'
import { splitEventsByLine, telemetryLineForRoute } from './eventLine'

const SESSION_KEY = 'sewpg.telemetry.session'
const FLUSH_INTERVAL_MS = 5000
const FLUSH_BATCH_SIZE = 20
const MAX_TEXT_LENGTH = 80
const MAX_ERROR_LENGTH = 500
const CLICK_SELECTOR =
  'button, a, [role="button"], [data-track], input[type="submit"], [role="tab"], [role="menuitem"]'

let started = false
let queue = []
let warned = false
let currentRoute = ''

const warnOnce = (message, error) => {
  if (warned) return
  warned = true
  console.warn(`[telemetry] ${message}`, error || '')
}

const truncate = (value, max = MAX_TEXT_LENGTH) => {
  const text = String(value ?? '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

const readSessionId = () => {
  try {
    const existing = window.sessionStorage.getItem(SESSION_KEY)
    if (existing) return existing
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `sess-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    window.sessionStorage.setItem(SESSION_KEY, id)
    return id
  } catch {
    return `sess-${Date.now()}`
  }
}

const readAuthToken = () => {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return typeof parsed?.token === 'string' ? parsed.token : ''
  } catch {
    return ''
  }
}

// 元素标识：最近的 data-track → 文本/aria-label → 简化 CSS 路径（tag#id.class，最多 3 层）
const describeNode = (node) => {
  const tag = node.tagName ? node.tagName.toLowerCase() : 'node'
  const id = node.id ? `#${node.id}` : ''
  const cls = node.classList?.[0] ? `.${node.classList[0]}` : ''
  return `${tag}${id}${cls}`
}

const cssPath = (el) => {
  const parts = []
  let node = el
  while (node && node !== document.body && parts.length < 3) {
    parts.unshift(describeNode(node))
    node = node.parentElement
  }
  return parts.join(' > ')
}

const enqueue = (event) => {
  try {
    // 归线按事件自身 route 在入队时固化，避免 flush 时刻按当前页面路径改判整批归属
    const route = event.route || window.location.pathname
    queue.push({
      sessionId: readSessionId(),
      eventType: event.eventType,
      route,
      line: telemetryLineForRoute(route),
      element: event.element || '',
      target: event.target || '',
      status: event.status || 'info',
      durationMs: event.durationMs ?? null,
      traceId: event.traceId || null,
      meta: event.meta || null,
      clientTs: new Date().toISOString(),
    })
    if (queue.length >= FLUSH_BATCH_SIZE) flush()
  } catch (error) {
    warnOnce('事件入队失败', error)
  }
}

// fetch keepalive 在页面 unload/hidden 时同样可靠，且能携带 Authorization（sendBeacon 不行），统一走它
const postEvents = (line, events, token) => {
  const url = `${ENV.API_BASE_URL}/${line}/events`
  const body = JSON.stringify({ events })
  try {
    window
      .fetch(url, {
        method: 'POST',
        body,
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
      })
      .catch((error) => warnOnce('事件上报失败', error))
  } catch (error) {
    warnOnce('事件上报失败', error)
  }
}

const flush = () => {
  if (!queue.length) return
  const token = readAuthToken()
  if (!token) {
    // 未登录时丢弃队列，不上报
    queue = []
    return
  }
  const events = queue
  queue = []
  // 按入队时固化的归线拆组，分别 POST 到各自线的 /events，跨线切换不再互相带走事件
  for (const [line, payloads] of splitEventsByLine(events)) {
    postEvents(line, payloads, token)
  }
}

const handleClick = (event) => {
  try {
    const el = event.target?.closest?.(CLICK_SELECTOR)
    if (!el) return
    const trackName = el.closest('[data-track]')?.getAttribute('data-track')
    const readable = trackName || el.getAttribute('aria-label') || el.innerText || el.value || ''
    const element = cssPath(el)
    enqueue({
      eventType: 'click',
      target: truncate(readable) || element,
      element,
      status: 'info',
    })
  } catch (error) {
    warnOnce('click 采集失败', error)
  }
}

const recordRoute = () => {
  try {
    const next = window.location.pathname
    if (next === currentRoute) return
    const from = currentRoute
    currentRoute = next
    enqueue({
      eventType: 'route',
      route: next,
      target: `${from} → ${next}`,
      status: 'info',
      meta: { from, to: next },
    })
  } catch (error) {
    warnOnce('route 采集失败', error)
  }
}

const wrapHistory = () => {
  ;['pushState', 'replaceState'].forEach((name) => {
    const original = window.history[name]
    if (typeof original !== 'function') return
    window.history[name] = function wrappedHistory(...args) {
      const result = original.apply(this, args)
      recordRoute()
      return result
    }
  })
}

const handleApiEvent = ({ method, path, status, durationMs, traceId }) => {
  try {
    const failed = !status || status >= 400
    enqueue({
      eventType: 'api',
      target: `${method} ${path}`,
      status: failed ? 'error' : 'success',
      durationMs,
      traceId,
      meta: { method, path, httpStatus: status },
    })
  } catch (error) {
    warnOnce('api 采集失败', error)
  }
}

const firstStackLine = (stack) =>
  truncate(String(stack || '').split('\n').find((line) => line.trim()) || '', MAX_ERROR_LENGTH)

const handleError = (event) => {
  try {
    enqueue({
      eventType: 'error',
      target: truncate(event.message || '未知错误', MAX_ERROR_LENGTH),
      status: 'error',
      meta: { stack: firstStackLine(event.error?.stack) },
    })
  } catch (error) {
    warnOnce('error 采集失败', error)
  }
}

const handleRejection = (event) => {
  try {
    const reason = event.reason
    const message = reason?.message || String(reason || '未处理的 Promise 拒绝')
    enqueue({
      eventType: 'error',
      target: truncate(message, MAX_ERROR_LENGTH),
      status: 'error',
      meta: { stack: firstStackLine(reason?.stack) },
    })
  } catch (error) {
    warnOnce('error 采集失败', error)
  }
}

// 在 App 顶层挂载一次；模块级 flag 保证 StrictMode 双调用/重复调用幂等
export function initTracker() {
  if (started || typeof window === 'undefined') return
  started = true
  currentRoute = window.location.pathname

  document.addEventListener('click', handleClick, true)
  wrapHistory()
  window.addEventListener('popstate', recordRoute)
  onApiEvent(handleApiEvent)
  window.addEventListener('error', handleError)
  window.addEventListener('unhandledrejection', handleRejection)

  window.setInterval(flush, FLUSH_INTERVAL_MS)
  window.addEventListener('beforeunload', flush)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
}
