import { useEffect, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import {
  appendDismissedKey,
  firstUndismissedStageFailure,
  loadDismissedKeys,
} from './materialPipelineFailures'

const POLL_MS = 5000
// 轮询连续失败达到阈值才提示「进度查询失败」：单次网络抖动不打扰页面。
const POLL_FAILURE_ALERT_THRESHOLD = 3
const TECHNICAL_BID_TYPE = '技术标'
const DISMISSED_KEYS_STORAGE_KEY = 'sewpg:technical-material-pipeline:dismissed'

const loadSessionDismissedKeys = () => {
  if (typeof window === 'undefined') return []
  try {
    return loadDismissedKeys(window.sessionStorage.getItem(DISMISSED_KEYS_STORAGE_KEY))
  } catch {
    return []
  }
}

// 素材流水线进度条（产品需求 2026-08-04）：上传 → 自动清洗 → 自动 Wiki 增量的统一进度，
// 挂在原始素材页与 Wiki 页顶部。任务全在后端执行，这里只轮询展示——切页、刷新浏览器
// 都不影响任务；空闲时整条不渲染，保持页面整洁。
// 失败/取消提示以后端记忆的「各阶段最近终态」为准（R10-B07-05），不要求本次会话曾看到
// 运行中：快速失败、失败后才进页面、清洗/深度解析失败都能持续展示，直到用户关闭、
// 重试成功或新任务终态覆盖。超大文件的预览要等后台深度解析，收尾必须如实：
// 队列已空但仍有待补全时不装作全部完成。
export default function MaterialPipelineProgress() {
  const [snapshot, setSnapshot] = useState(null)
  const [dismissedKeys, setDismissedKeys] = useState(loadSessionDismissedKeys)
  const [pollFailures, setPollFailures] = useState(0)
  const [pollAlertDismissed, setPollAlertDismissed] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState('')

  useEffect(() => {
    try {
      window.sessionStorage.setItem(DISMISSED_KEYS_STORAGE_KEY, JSON.stringify(dismissedKeys))
    } catch {
      // sessionStorage 被禁用或配额用尽时仅退化为当前组件内关闭。
    }
  }, [dismissedKeys])

  useEffect(() => {
    let cancelled = false
    let timer = null
    const poll = async () => {
      try {
        const payload = await technicalMaterialsAPI.pipelineProgress()
        if (cancelled) return
        setSnapshot(payload)
        // 查询恢复后清零并重新武装提示：之后再次连续失败会重新提醒。
        setPollFailures(0)
        setPollAlertDismissed(false)
      } catch {
        // 单次轮询失败保持上次快照；连续失败由阈值提示接管，不再静默。
        if (!cancelled) setPollFailures((count) => count + 1)
      } finally {
        // 上一次请求完成后再计时，避免慢网络下 setInterval 叠加请求并乱序覆盖快照。
        if (!cancelled) timer = window.setTimeout(poll, POLL_MS)
      }
    }
    poll()
    return () => {
      cancelled = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [])

  // 与 Wiki 页「刷新并重试」同一入口：refresh 会重试待重试预览，并补排深度解析。
  const handleRetry = async () => {
    setRetrying(true)
    setRetryError('')
    try {
      await technicalMaterialsAPI.wiki.bootstrap({ mode: 'refresh', bidType: TECHNICAL_BID_TYPE })
      // 后端已接受补跑后立即进入进度态，不让旧失败在下一次轮询前继续假装可重试。
      setSnapshot((current) => ({
        ...(current || {}),
        wiki: { ...(current?.wiki || {}), status: 'running' },
      }))
    } catch (error) {
      setRetryError(error?.payload?.detail || error?.message || '重试启动失败，请稍后重试。')
    } finally {
      setRetrying(false)
    }
  }

  const dismiss = (key) => {
    setDismissedKeys((keys) => appendDismissedKey(keys, key))
  }

  const cleaningRemaining = Number(snapshot?.cleaning?.active || 0)
  const deepParseRemaining = Number(snapshot?.deepParse?.active || 0)
  const pendingPreview = Number(snapshot?.pendingPreview || 0)
  const wiki = snapshot?.wiki || {}
  const wikiRunning = wiki.status === 'running'

  // 进度接口连续不可用：显式提示，不再静默保持旧快照或空白（R10-B07-05）。
  if (pollFailures >= POLL_FAILURE_ALERT_THRESHOLD && !pollAlertDismissed) {
    return (
      <div role="alert" className="flex items-center gap-3 rounded-md border border-error/30 bg-error/5 px-4 py-2.5 text-[13px]">
        <span aria-hidden="true" className="material-symbols-outlined text-[16px] text-error">sync_problem</span>
        <span className="min-w-0 flex-1 truncate text-on-surface">
          素材流水线进度查询失败，正在自动重试；也可刷新页面重连。
        </span>
        <button
          type="button"
          onClick={() => setPollAlertDismissed(true)}
          aria-label="关闭查询失败提示"
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-on-surface"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[15px]">close</span>
        </button>
      </div>
    )
  }

  if (!snapshot) return null

  // 空闲收尾：任一阶段最近终态是失败/取消时持续展示，直到用户关闭、重试成功或被新终态覆盖。
  if (!cleaningRemaining && !deepParseRemaining && !wikiRunning) {
    const failure = firstUndismissedStageFailure(snapshot, dismissedKeys, TECHNICAL_BID_TYPE)
    if (failure) {
      const statusText = failure.status === 'cancelled' ? '已取消' : '失败'
      return (
        <div role="alert" className="flex items-center gap-3 rounded-md border border-error/30 bg-error/5 px-4 py-2.5 text-[13px]">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px] text-error">error</span>
          <span className="min-w-0 flex-1 truncate text-on-surface" title={failure.message || ''}>
            {`${failure.stageLabel}${statusText}${failure.message ? `：${failure.message}` : ''}`}
            {failure.jobId ? `（任务编号：${failure.jobId}）` : ''}
            {!failure.retryable && failure.status === 'failed' ? '——可在素材库重新上传该文件后自动重新处理' : ''}
            {retryError ? `；${retryError}` : ''}
          </span>
          {failure.retryable ? (
            <button
              type="button"
              onClick={handleRetry}
              disabled={retrying}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-error/30 px-2 py-0.5 text-xs text-error hover:bg-error/10 disabled:opacity-50"
            >
              <span aria-hidden="true" className={`material-symbols-outlined text-[14px] ${retrying ? 'animate-spin' : ''}`}>
                refresh
              </span>
              {retrying ? '重试启动中…' : '重试'}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => {
              dismiss(failure.dismissKey)
              setRetryError('')
            }}
            aria-label="关闭任务提示"
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-on-surface"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[15px]">close</span>
          </button>
        </div>
      )
    }
    // 收尾如实：队列已空但仍有预览停在兜底态时说清还差几个，不装作全部完成。
    if (pendingPreview > 0 && !dismissedKeys.includes(`pending:${pendingPreview}`)) {
      return (
        <div role="status" className="flex items-center gap-3 rounded-md border border-surface-container-high bg-surface-container-lowest px-4 py-2.5 text-[13px]">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px] text-outline">pending</span>
          <span className="min-w-0 flex-1 truncate text-on-surface">
            {pendingPreview} 个大文件的预览待补全——深度解析产物就绪后自动补齐，也可在 Wiki 页点「刷新并重试」
          </span>
          <button
            type="button"
            onClick={() => dismiss(`pending:${pendingPreview}`)}
            aria-label="关闭待补全提示"
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-on-surface"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[15px]">close</span>
          </button>
        </div>
      )
    }
    return null
  }

  const progress = wiki.progress && typeof wiki.progress === 'object' ? wiki.progress : {}
  const phase = String(progress.phase || '')
  const stageDone = Number(progress.done || 0)
  const stageTotal = Number(progress.total || 0)
  const cleaningTotal = Number(snapshot?.cleaning?.total || 0)
  const cleaningDone = Number(snapshot?.cleaning?.done || 0)
  // 各段统一用 m/n 呈现；分母缺失（如清洗批次总量未记录）时退化为纯文字，不编数字。
  const ratio = (done, total) => (total > 0 ? ` ${Math.min(done, total)}/${total}` : '')

  // 流水线状态：清洗 → AI 预览 → 建树导入；深度解析段只在真有解析任务时才出现——
  // 它是超大文件才走的支线，常态挂一个灰段只会变成噪音。
  const previewActive = wikiRunning && (phase === 'preview' || !phase)
  const mirrorActive = wikiRunning && (phase === 'build' || phase === 'import')
  const deepParseActive = deepParseRemaining > 0 && !wikiRunning
  const stages = [
    {
      key: 'clean',
      label: `清洗${cleaningRemaining > 0 ? ratio(cleaningDone, cleaningTotal) || ` · 剩余 ${cleaningRemaining}` : ''}`,
      state: cleaningRemaining > 0 ? 'active' : 'done',
    },
    {
      key: 'preview',
      label: `AI 预览${previewActive ? ratio(stageDone, stageTotal) : ''}`,
      state: previewActive ? 'active' : mirrorActive || deepParseActive ? 'done' : 'pending',
    },
    {
      key: 'mirror',
      label: phase === 'import' ? `导入 Wiki${ratio(stageDone, stageTotal)}` : '建树导入',
      state: mirrorActive ? 'active' : deepParseActive ? 'done' : 'pending',
    },
    ...(deepParseRemaining > 0
      ? [{
        key: 'deep',
        label: `深度解析 · 剩余 ${deepParseRemaining}`,
        state: deepParseActive ? 'active' : 'pending',
      }]
      : []),
  ]

  // 进度条：分母缺失或深度解析中用流动条；有计数时按 清洗占 0-20%、预览 20-80%、导入 80-96% 折算。
  const indeterminate = deepParseActive
    || (cleaningRemaining > 0 && !cleaningTotal)
    || (previewActive && !stageTotal)
  let percent = 0
  if (cleaningRemaining > 0) {
    percent = cleaningTotal > 0 ? Math.round((Math.min(cleaningDone, cleaningTotal) / cleaningTotal) * 20) : 0
  } else if (previewActive) {
    percent = stageTotal > 0 ? 20 + Math.round((Math.min(stageDone, stageTotal) / stageTotal) * 60) : 20
  } else if (mirrorActive) {
    percent = phase === 'import' && stageTotal > 0
      ? 80 + Math.round((Math.min(stageDone, stageTotal) / stageTotal) * 16)
      : 80
  }

  return (
    <div
      role="status"
      className="business-panel flex flex-col gap-2 rounded-md border border-surface-container-high bg-surface-container-lowest px-4 py-2.5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] leading-[1.6]">
        <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[16px] text-primary">
          progress_activity
        </span>
        <span className="font-medium text-on-surface">素材流水线</span>
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          {stages.map((stage, index) => (
            <span key={stage.key} className="flex items-center gap-1.5">
              {index > 0 ? (
                <span aria-hidden="true" className="material-symbols-outlined text-[13px] text-outline/60">chevron_right</span>
              ) : null}
              <span
                className={`inline-flex items-center gap-1 text-xs ${
                  stage.state === 'active'
                    ? 'font-semibold text-primary'
                    : stage.state === 'done'
                      ? 'text-secondary'
                      : 'text-outline'
                }`}
              >
                {stage.state === 'done' ? (
                  <span aria-hidden="true" className="material-symbols-outlined text-[13px]">check_circle</span>
                ) : stage.state === 'active' ? (
                  <span aria-hidden="true" className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                ) : (
                  <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-outline/40" />
                )}
                {stage.label}
              </span>
            </span>
          ))}
        </div>
        <span className="ml-auto text-xs text-outline">后台执行 · 可离开本页</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-container-high">
        {indeterminate ? (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-primary/60" />
        ) : (
          <div
            className="h-full rounded-full bg-primary transition-all duration-700 ease-out"
            style={{ width: `${Math.max(percent, 4)}%` }}
          />
        )}
      </div>
    </div>
  )
}
