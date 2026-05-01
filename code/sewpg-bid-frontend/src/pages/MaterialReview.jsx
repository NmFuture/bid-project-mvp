import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { reviewAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/shared/OnlyOfficeWorkspace'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const statusConfig = {
  resolved: {
    label: '已补录',
    badgeClass: 'bg-secondary-container text-on-secondary-container',
  },
  skipped: {
    label: '未补录',
    badgeClass: 'bg-error-container text-on-error-container',
  },
  checking: {
    label: '待核对',
    badgeClass: 'bg-tertiary-fixed text-on-tertiary-fixed',
  },
  pending: {
    label: '待补录',
    badgeClass: 'bg-surface-container-high text-on-surface-variant',
  },
}

const formatDateTime = (value) => {
  if (!value) return '未确认'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未确认'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function MaterialReview({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [reviewDoc, setReviewDoc] = useState(null)
  const [fallbackContent, setFallbackContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [docError, setDocError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [savingFallback, setSavingFallback] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, reviewDocPayload] = await Promise.all([
        reviewAPI.list(id),
        reviewAPI.document(id).catch((docErr) => ({ __error: docErr })),
      ])
      setData(payload)
      if (reviewDocPayload?.__error) {
        setReviewDoc(null)
        setFallbackContent('')
        setOnlyofficeError('')
        setDocError(reviewDocPayload.__error?.message || 'S6 解析文档暂未就绪')
      } else {
        setReviewDoc(reviewDocPayload)
        setFallbackContent(reviewDocPayload?.fallback?.content || '')
        setDocError('')
        setOnlyofficeError('')
      }
    } catch (e) {
      setError(e?.message || 'S6 审核清单加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const items = useMemo(() => data?.items || [], [data])
  const summary = data?.summary || {
    total: items.length,
    resolvedCount: 0,
    skippedCount: 0,
    pendingCount: items.length,
  }
  const canConfirm = data?.status === 'ready' && summary.pendingCount === 0 && items.length > 0
  const confirmDisabledReason = data?.status !== 'ready'
    ? '请先在 S5 完成并提交审核'
    : summary.pendingCount > 0
      ? `仍有 ${summary.pendingCount} 项待处理`
      : items.length === 0
        ? '暂无可审核素材'
        : ''

  const handleConfirmAndNext = async () => {
    if (!canConfirm) {
      showToast?.(confirmDisabledReason || '当前不可进入下一阶段', 'error')
      return
    }

    setConfirming(true)
    try {
      const response = await reviewAPI.confirm(id)
      if (response?.payload) {
        setData(response.payload)
      }
      await stagesAPI.update(id, 6, { status: 'completed' })
      showToast?.('S6 审核完成，已进入 S7 填充')
      navigate(projectRoute(id, '/generate', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || 'S6 审核确认失败，请稍后重试', 'error')
    } finally {
      setConfirming(false)
    }
  }

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await reviewAPI.saveDocument(id, { content })
      setReviewDoc(response?.payload || reviewDoc)
      showToast?.(response?.message || 'S6 预览文档已保存')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const hasOnlyOfficeSession = Boolean(reviewDoc?.onlyoffice?.fileUrl && reviewDoc?.onlyoffice?.callbackUrl)
  const useFallbackPreview = !hasOnlyOfficeSession || Boolean(onlyofficeError)

  if (loading) return <PageLoading title="正在加载 S6 审核清单..." />

  if (error) {
    return (
      <PageError
        title="S6 审核清单加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleConfirmAndNext}
              disabled={!canConfirm || confirming}
              title={confirmDisabledReason}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {confirming ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <OnlyOfficeWorkspace
        heightClass="min-h-[720px]"
        gridClassName="xl:grid-cols-[minmax(22rem,32rem)_minmax(0,1fr)]"
        documentTitle="解析文档预览"
        documentSubtitle={reviewDoc?.fileName || 'S6 解析文档暂未就绪'}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${(reviewDoc?.parseStatus || data?.parse?.status) === 'completed' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {(reviewDoc?.parseStatus || data?.parse?.status) === 'completed' ? '解析完成' : '待解析'}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-surface-container-high bg-surface-container-low px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-on-surface">审核上下文</h3>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${data?.confirmed ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                  {data?.confirmed ? '已确认' : '待确认'}
                </span>
              </div>
              <p className="mt-1 text-xs text-outline">审核时间：{formatDateTime(data?.reviewedAt)}</p>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <span className="rounded-md bg-surface-container-low px-3 py-2 font-semibold text-on-surface-variant">总计 {summary.total}</span>
                <span className="rounded-md bg-secondary-container px-3 py-2 font-semibold text-on-secondary-container">已补录 {summary.resolvedCount}</span>
                <span className="rounded-md bg-error-container px-3 py-2 font-semibold text-on-error-container">未补录 {summary.skippedCount}</span>
                <span className="rounded-md bg-tertiary-fixed px-3 py-2 font-semibold text-on-tertiary-fixed">待处理 {summary.pendingCount}</span>
              </div>

              {!items.length ? (
                <div className="rounded-md border border-dashed border-surface-container-high px-4 py-8 text-center">
                  <span className="material-symbols-outlined text-4xl text-outline">inventory_2</span>
                  <h4 className="mt-3 text-sm font-semibold text-on-surface">暂无审核素材</h4>
                  <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
                    当前没有需要审核的备料项，请先在 S5 补录并提交审核。
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {items.map((item) => {
                    const cfg = statusConfig[item.status] || statusConfig.pending
                    return (
                      <div key={item.id} className="rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <h4 className="break-words text-sm font-semibold text-on-surface">{item.title || '-'}</h4>
                            <p className="mt-1 text-xs text-on-surface-variant">{item.section || '-'}</p>
                          </div>
                          <span className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${cfg.badgeClass}`}>
                            {cfg.label}
                          </span>
                        </div>
                        {item.status === 'resolved' ? (
                          <div className="mt-3 space-y-1 text-xs">
                            <div className="text-on-surface">{item.resolvedSource || item.submission?.fileName || '已补录'}</div>
                            <div className="break-all text-outline">{item.submission?.storedPath || '-'}</div>
                            <div className="text-outline">{item.submission?.submittedAt || item.resolvedAt || '-'}</div>
                          </div>
                        ) : null}
                        {item.status === 'skipped' ? (
                          <p className="mt-3 text-xs text-on-surface-variant">未补录原因：{item.skipReason || '未填写'}</p>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      >
        {!reviewDoc ? (
          <div className="flex min-h-[560px] flex-1 items-center justify-center rounded-md border border-dashed border-surface-container-high px-6 text-center text-sm text-on-surface-variant">
            {docError || 'S6 解析文档暂未就绪。请先在 S5 点击“提交至 S6 审核”触发解析。'}
          </div>
        ) : (
          <>
            {(docError || onlyofficeError) && (
              <div className="mb-3 rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
                {docError || onlyofficeError}
              </div>
            )}

            <div className={useFallbackPreview ? 'hidden' : 'min-h-0 flex-1'}>
              <OnlyOfficeEmbed
                session={reviewDoc?.onlyoffice}
                mode="view"
                className="h-full min-h-[560px] w-full rounded-md border border-outline-variant bg-white"
                onReady={() => setOnlyofficeError('')}
                onError={(message) => setOnlyofficeError(message)}
              />
            </div>

            <div className={useFallbackPreview ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
              <textarea
                value={fallbackContent}
                onChange={(event) => setFallbackContent(event.target.value)}
                className="min-h-[520px] flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <div className="flex justify-end">
                <button
                  onClick={handleSaveFallback}
                  disabled={savingFallback}
                  className="flex h-8 items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingFallback ? '保存中...' : '保存回写'}
                </button>
              </div>
            </div>
          </>
        )}
      </OnlyOfficeWorkspace>
    </div>
  )
}
