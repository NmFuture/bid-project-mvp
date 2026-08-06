import { useEffect, useRef, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import { createWikiJobSuccessTracker } from './wikiJobSuccessTracker'

const POLL_MS = 5000

const pipelineRunning = (payload) => (
  Number(payload?.cleaning?.active || 0) > 0
  || Number(payload?.deepParse?.active || 0) > 0
  || payload?.wiki?.status === 'running'
)

// 素材流水线进度条（产品需求 2026-08-04）：上传 → 自动清洗 → 自动 Wiki 增量的统一进度，
// 挂在原始素材页与 Wiki 页顶部。任务全在后端执行，这里只轮询展示——切页、刷新浏览器
// 都不影响任务；空闲时整条不渲染，保持页面整洁。失败提示仅在本次会话观察到运行后展示，可关闭。
// 超大文件的预览要等后台深度解析，收尾必须如实：队列已空但仍有待补全时不装作全部完成。
// onWikiJobSuccess：观察到一个 Wiki 任务从运行变为成功时回调一次（按 jobId 去重），
// 供 Wiki 页面在自动任务完成后重新加载目录树（R10-B07-04）。
export default function MaterialPipelineProgress({ onWikiJobSuccess }) {
  const [snapshot, setSnapshot] = useState(null)
  const [dismissedJobId, setDismissedJobId] = useState('')
  const [sawRunning, setSawRunning] = useState(false)
  // 跨轮询记住「运行 → 成功」跳变状态；回调经 ref 取最新值，轮询 effect 不随渲染重建。
  const [trackWikiJobSuccess] = useState(createWikiJobSuccessTracker)
  const onWikiJobSuccessRef = useRef(onWikiJobSuccess)
  useEffect(() => {
    onWikiJobSuccessRef.current = onWikiJobSuccess
  })

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const payload = await technicalMaterialsAPI.pipelineProgress()
        if (cancelled) return
        setSnapshot(payload)
        if (pipelineRunning(payload)) setSawRunning(true)
        const succeededJobId = trackWikiJobSuccess(payload?.wiki)
        if (succeededJobId) onWikiJobSuccessRef.current?.(succeededJobId)
      } catch {
        // 轮询失败保持上次快照，不打扰页面。
      }
    }
    poll()
    const timer = window.setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [trackWikiJobSuccess])

  const cleaningRemaining = Number(snapshot?.cleaning?.active || 0)
  const deepParseRemaining = Number(snapshot?.deepParse?.active || 0)
  const pendingPreview = Number(snapshot?.pendingPreview || 0)
  const wiki = snapshot?.wiki || {}
  const wikiRunning = wiki.status === 'running'
  const wikiFailed = wiki.status === 'failed'

  if (!snapshot) return null

  // 失败横幅：本次会话看到过流水线运行、且未被关闭时展示。
  if (!cleaningRemaining && !deepParseRemaining && !wikiRunning) {
    if (wikiFailed && sawRunning && dismissedJobId !== String(wiki.jobId || 'failed')) {
      return (
        <div role="alert" className="flex items-center gap-3 rounded-md border border-error/30 bg-error/5 px-4 py-2.5 text-[13px]">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px] text-error">error</span>
          <span className="min-w-0 flex-1 truncate text-on-surface" title={wiki.message || ''}>
            Wiki 增量构建失败{wiki.message ? `：${wiki.message}` : ''}——可在 Wiki 页点「刷新并重试」
          </span>
          <button
            type="button"
            onClick={() => setDismissedJobId(String(wiki.jobId || 'failed'))}
            aria-label="关闭失败提示"
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-on-surface"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[15px]">close</span>
          </button>
        </div>
      )
    }
    // 收尾如实：队列已空但仍有预览停在兜底态时说清还差几个，不装作全部完成。
    if (pendingPreview > 0 && dismissedJobId !== `pending:${pendingPreview}`) {
      return (
        <div role="status" className="flex items-center gap-3 rounded-md border border-surface-container-high bg-surface-container-lowest px-4 py-2.5 text-[13px]">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px] text-outline">pending</span>
          <span className="min-w-0 flex-1 truncate text-on-surface">
            {pendingPreview} 个大文件的预览待补全——深度解析产物就绪后自动补齐，也可在 Wiki 页点「刷新并重试」
          </span>
          <button
            type="button"
            onClick={() => setDismissedJobId(`pending:${pendingPreview}`)}
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
