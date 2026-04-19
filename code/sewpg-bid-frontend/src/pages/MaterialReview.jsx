import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { reviewAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

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
  const [data, setData] = useState(null)
  const [reviewDoc, setReviewDoc] = useState(null)
  const [fallbackContent, setFallbackContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [docError, setDocError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [forceSavingDoc, setForceSavingDoc] = useState(false)
  const [savingFallback, setSavingFallback] = useState(false)
  const [onlyofficeError, setOnlyofficeError] = useState('')

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
        setDocError(reviewDocPayload.__error?.message || 'S6 解析文档暂未就绪')
      } else {
        setReviewDoc(reviewDocPayload)
        setFallbackContent(reviewDocPayload?.fallback?.content || '')
        setDocError('')
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
  const hasOnlyOfficeSession = Boolean(reviewDoc?.onlyoffice?.fileUrl && reviewDoc?.onlyoffice?.callbackUrl)
  const useFallbackPreview = !hasOnlyOfficeSession || Boolean(onlyofficeError)
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
      navigate(`/projects/${id}/generate`)
    } catch (e) {
      showToast?.(e?.message || 'S6 审核确认失败，请稍后重试', 'error')
    } finally {
      setConfirming(false)
    }
  }

  const handleForceSaveDoc = async () => {
    if (!reviewDoc) return
    setForceSavingDoc(true)
    try {
      const response = await reviewAPI.forceSaveDocument(id)
      setReviewDoc(response?.payload || reviewDoc)
      showToast?.(response?.message || '已触发保存回写')
    } catch (e) {
      showToast?.(e?.message || '保存回写失败，请稍后重试', 'error')
    } finally {
      setForceSavingDoc(false)
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
    <div className="flex flex-col gap-6 animate-fade-in max-w-6xl mx-auto w-full">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        title="S6 审核备料"
        description="仅展示缺失素材、补录情况与未补录原因。进入 S6 时会自动触发后端解析，并在下方预览解析 Word。"
        leftExtra={(
          <button
            onClick={() => window.history.back()}
            className="text-primary hover:bg-surface-container-low rounded-full w-10 h-10 flex items-center justify-center transition-colors"
          >
            <span className="material-symbols-outlined">arrow_back</span>
          </button>
        )}
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">refresh</span>
              刷新
            </button>
            <button
              onClick={handleConfirmAndNext}
              disabled={!canConfirm || confirming}
              title={confirmDisabledReason}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
              {confirming ? '进入中...' : '审核无误，进入下一阶段（S7）'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[420px]">
        <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-surface-container-high text-on-surface-variant">
                总计 {summary.total}
              </span>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-secondary-container text-on-secondary-container">
                已补录 {summary.resolvedCount}
              </span>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-error-container text-on-error-container">
                未补录 {summary.skippedCount}
              </span>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-tertiary-fixed text-on-tertiary-fixed">
                待处理 {summary.pendingCount}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-outline">审核时间：{formatDateTime(data?.reviewedAt)}</span>
              <span className={`px-2.5 py-1 rounded-full font-semibold ${data?.confirmed ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                {data?.confirmed ? '已确认' : '待确认'}
              </span>
            </div>
          </div>
        </div>

        {!items.length ? (
          <div className="h-[320px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">inventory_2</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">暂无审核素材</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              当前没有需要审核的备料项，请先在 S5 补录并提交审核。
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-container-low border-b border-surface-container-high">
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">缺失素材</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">所属分区</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">补录状态</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">补录情况</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">未补录原因</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const cfg = statusConfig[item.status] || statusConfig.pending
                  return (
                    <tr key={item.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                      <td className="px-6 py-3 text-on-surface font-medium min-w-[220px]">{item.title || '-'}</td>
                      <td className="px-6 py-3 text-on-surface-variant min-w-[180px]">{item.section || '-'}</td>
                      <td className="px-6 py-3 whitespace-nowrap">
                        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${cfg.badgeClass}`}>
                          {cfg.label}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-on-surface min-w-[220px]">
                        {item.status === 'resolved' ? (
                          <div className="flex flex-col gap-1 text-xs">
                            <span className="text-on-surface">{item.resolvedSource || item.submission?.fileName || '已补录'}</span>
                            <span className="text-outline break-all">{item.submission?.storedPath || '-'}</span>
                            <span className="text-outline">{item.submission?.submittedAt || item.resolvedAt || '-'}</span>
                          </div>
                        ) : '-'}
                      </td>
                      <td className="px-6 py-3 text-on-surface-variant min-w-[220px]">
                        {item.status === 'skipped' ? (item.skipReason || '未填写') : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </DataCard>

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1 text-sm">
            <div className="text-on-surface">
              <span className="text-on-surface-variant">S6 解析文档：</span>
              <span className="font-medium">{reviewDoc?.fileName || '-'}</span>
            </div>
            <div className="text-on-surface">
              <span className="text-on-surface-variant">解析时间：</span>
              <span>{formatDateTime(reviewDoc?.parsedAt || data?.parse?.parsedAt)}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`px-2.5 py-1 rounded-full font-semibold ${(reviewDoc?.parseStatus || data?.parse?.status) === 'completed' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
              {(reviewDoc?.parseStatus || data?.parse?.status) === 'completed' ? '解析完成' : '待解析'}
            </span>
            {reviewDoc && (
              <button
                onClick={handleForceSaveDoc}
                disabled={forceSavingDoc}
                className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-semibold hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {forceSavingDoc ? '保存中...' : '触发保存回写'}
              </button>
            )}
          </div>
        </div>

        {docError && (
          <div className="px-6 pt-4">
            <div className="rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">{docError}</div>
          </div>
        )}

        {!reviewDoc ? (
          <div className="h-[280px] px-6 py-8 flex items-center justify-center text-center text-sm text-on-surface-variant">
            S6 解析文档暂未就绪。请先在 S5 点击“提交至 S6 审核”触发解析。
          </div>
        ) : (
          <div className="p-4 flex flex-col gap-3">
            <div className="text-xs text-on-surface-variant">
              {useFallbackPreview
                ? hasOnlyOfficeSession
                  ? 'OnlyOffice 预览初始化失败，已切换为文本预览兜底模式。'
                  : '当前未拿到可用的 OnlyOffice 会话，已切换为文本预览兜底模式。'
                : 'S6 审核备料文档预览已接入 OnlyOffice（同 S9 预留挂载接口）。'}
            </div>
            {onlyofficeError && (
              <div className="rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">
                {onlyofficeError}
              </div>
            )}

            <div className={useFallbackPreview ? 'hidden' : 'block'}>
              <div className="h-[60vh] rounded-lg border border-surface-container-high overflow-hidden bg-surface-container-low">
                <OnlyOfficeEmbed
                  session={reviewDoc?.onlyoffice}
                  mode="view"
                  className="w-full h-full border-0 bg-white"
                  onReady={() => setOnlyofficeError('')}
                  onError={(message) => setOnlyofficeError(message)}
                />
              </div>
            </div>

            <div className={useFallbackPreview ? 'flex flex-col gap-3' : 'hidden'}>
              <textarea
                value={fallbackContent}
                onChange={(event) => setFallbackContent(event.target.value)}
                className="w-full h-[46vh] rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <div className="flex justify-end">
                <button
                  onClick={handleSaveFallback}
                  disabled={savingFallback}
                  className="px-4 py-2 text-sm font-semibold rounded-lg bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingFallback ? '保存中...' : '保存回写'}
                </button>
              </div>
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
