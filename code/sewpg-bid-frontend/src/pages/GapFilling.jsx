import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI, reviewAPI, stagesAPI } from '../api'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import { PageLoading, PageError } from '../components/states/PageState'

const MAX_FILE_SIZE = 500 * 1024 * 1024
const MAX_BATCH_FILES = 5
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const statusConfig = {
  pending: { icon: 'error', color: 'text-error', label: '待补录' },
  checking: { icon: 'warning', color: 'text-tertiary', label: '待核对' },
  resolved: { icon: 'check_circle', color: 'text-secondary', label: '已补录' },
  skipped: { icon: 'do_not_disturb_on', color: 'text-outline', label: '已跳过' },
}

const extOf = (name) => {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

const detectBidType = (gap) => {
  const text = `${gap?.section || ''} ${gap?.title || ''}`
  if (text.includes('商务')) return '商务标'
  if (text.includes('通用')) return '通用'
  return '技术标'
}

export default function GapFilling({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [selectedGapId, setSelectedGapId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingGap, setSavingGap] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [submittingReview, setSubmittingReview] = useState(false)
  const [showSkipModal, setShowSkipModal] = useState(false)
  const [skipReason, setSkipReason] = useState('')
  const [conflictContext, setConflictContext] = useState(null)
  const fileInputRef = useRef(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [gapsPayload, submissionsPayload] = await Promise.all([
        gapsAPI.list(id),
        gapsAPI.submissions(id).catch(() => ({ items: [] })),
      ])
      const list = gapsPayload?.items || []
      setData({
        ...gapsPayload,
        submissions: submissionsPayload?.items || [],
      })
      setSelectedGapId((prev) => (list.some((item) => item.id === prev) ? prev : list[0]?.id || ''))
    } catch (e) {
      setError(e?.message || 'S5 备料清单加载失败')
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
  const submissions = useMemo(() => data?.submissions || [], [data])

  const selectedGap = useMemo(() => {
    if (!items.length) return null
    return items.find((item) => item.id === selectedGapId) || items[0]
  }, [items, selectedGapId])

  const selectedGapSubmissions = useMemo(() => {
    if (!selectedGap) return []
    return submissions
      .filter((item) => item.missingId === selectedGap.id)
      .sort((a, b) => String(b.submittedAt || '').localeCompare(String(a.submittedAt || '')))
  }, [selectedGap, submissions])

  const latestSubmission = selectedGapSubmissions[0] || null
  const pendingCount = items.filter((item) => !['resolved', 'skipped'].includes(item.status)).length
  const submitEnabled = items.length > 0 && pendingCount === 0
  const submitDisabledReason = !items.length
    ? '暂无可提交项'
    : pendingCount > 0
      ? `仍有 ${pendingCount} 项未处理，无法提交审核`
      : ''

  const updateGapInState = (gapId, patch) => {
    setData((prev) => ({
      ...prev,
      items: (prev?.items || []).map((item) => (item.id === gapId ? { ...item, ...patch } : item)),
    }))
  }

  const submitMaterial = async (payload) => {
    const response = await gapsAPI.submitMaterial(id, payload)
    const nextItems = response?.payload?.items || data?.items || []
    const nextSubmissions = response?.payload?.submissions || data?.submissions || []
    setData((prev) => ({
      ...prev,
      items: nextItems,
      submissions: nextSubmissions,
    }))
    return response
  }

  const handleUploadChange = async (event) => {
    const files = Array.from(event?.target?.files || [])
    if (!selectedGap || !files.length) return

    if (files.length > MAX_BATCH_FILES) {
      showToast(`单次最多上传 ${MAX_BATCH_FILES} 个文件`, 'error')
      return
    }

    for (const file of files) {
      if (Number(file.size || 0) > MAX_FILE_SIZE) {
        showToast(`文件 ${file.name} 超过 500MB 上限`, 'error')
        return
      }
      if (!ALLOWED_EXTENSIONS.has(extOf(file.name))) {
        showToast(`文件 ${file.name} 类型不在白名单`, 'error')
        return
      }
    }

    const payload = {
      missingId: selectedGap.id,
      bidType: selectedGap.bidType || detectBidType(selectedGap),
      onConflict: undefined,
      files: files.map((file) => ({
        name: file.name,
        size: Number(file.size || 0),
        type: file.type || '',
      })),
    }

    setUploading(true)
    try {
      const result = await submitMaterial(payload)
      showToast(result?.message || `已提交 ${files.length} 个文件`)
      setConflictContext(null)
    } catch (e) {
      if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
        setConflictContext({
          payload,
          detail: e?.payload?.conflict || null,
        })
      } else {
        showToast(e?.message || '提交失败，请重试', 'error')
      }
    } finally {
      setUploading(false)
      if (event?.target) event.target.value = ''
    }
  }

  const resolveUploadConflict = async (action) => {
    if (!conflictContext?.payload) return
    setUploading(true)
    try {
      const result = await submitMaterial({
        ...conflictContext.payload,
        onConflict: action,
      })
      showToast(result?.message || '冲突处理成功')
      setConflictContext(null)
    } catch (e) {
      showToast(e?.message || '冲突处理失败', 'error')
    } finally {
      setUploading(false)
    }
  }

  const handleResolve = async () => {
    if (!selectedGap) return
    if (selectedGap.status === 'resolved') {
      showToast('该缺口已补录完成')
      return
    }
    if (!latestSubmission) {
      showToast('请先上传并提交补录素材', 'error')
      return
    }

    setSavingGap(true)
    try {
      await gapsAPI.update(id, selectedGap.id, {
        action: 'resolve',
        source: {
          name: latestSubmission.fileName || latestSubmission.fileId || '已补录',
          receiptId: latestSubmission.receiptId,
        },
      })
      updateGapInState(selectedGap.id, {
        status: 'resolved',
        resolvedSource: latestSubmission.fileName || latestSubmission.fileId || '已补录',
        skipReason: '',
      })
      showToast('缺口已标记为已补录')
    } catch (e) {
      showToast(e?.message || '补录状态保存失败', 'error')
    } finally {
      setSavingGap(false)
    }
  }

  const openSkipDialog = () => {
    if (!selectedGap) return
    setSkipReason(selectedGap.skipReason || '')
    setShowSkipModal(true)
  }

  const handleSkip = async () => {
    if (!selectedGap) return
    const reason = skipReason.trim()
    if (!reason) {
      showToast('未补录原因不能为空', 'error')
      return
    }

    setSavingGap(true)
    try {
      await gapsAPI.updateMissing(id, selectedGap.id, { status: 'skipped', reason })
      updateGapInState(selectedGap.id, {
        status: 'skipped',
        skipReason: reason,
        resolvedSource: '',
      })
      setShowSkipModal(false)
      showToast('已记录未补录原因')
    } catch (e) {
      showToast(e?.message || '保存失败', 'error')
    } finally {
      setSavingGap(false)
    }
  }

  const handleSubmitReview = async () => {
    if (!submitEnabled) {
      showToast(submitDisabledReason, 'error')
      return
    }

    setSubmittingReview(true)
    try {
      await gapsAPI.submitReview(id)
      const prepareResponse = await reviewAPI.prepareParse(id)
      await stagesAPI.update(id, 5, { status: 'completed' })
      showToast(prepareResponse?.message || 'S5 已提交审核并触发 S6 解析，已进入 S6')
      navigate(`/projects/${id}/gaps/review`)
    } catch (e) {
      showToast(e?.message || '提交审核失败，请稍后重试', 'error')
    } finally {
      setSubmittingReview(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S5 备料补交..." />

  if (error) {
    return (
      <PageError
        title="S5 备料补交加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <div className="flex items-center gap-4">
        <button onClick={() => window.history.back()} className="text-primary hover:bg-surface-container-low rounded-full w-10 h-10 flex items-center justify-center transition-colors">
          <span className="material-symbols-outlined">arrow_back</span>
        </button>
        <div>
          <h1 className="text-2xl font-headline font-bold text-primary">S5 备料补交</h1>
          <p className="text-sm text-on-surface-variant">仅保留缺失素材清单与文件提交模块，并生成补料回执。</p>
        </div>
        <span className="ml-2 px-3 py-1 bg-error-container text-on-error-container text-sm font-bold rounded-full">{items.length} 项缺失</span>
        <button
          onClick={handleSubmitReview}
          disabled={!submitEnabled || submittingReview}
          title={submitDisabledReason}
          className="ml-auto px-4 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submittingReview ? '提交中...' : '提交至 S6 审核'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 min-h-[600px]">
        <div className="bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          <div className="px-6 py-4 border-b border-surface-container-high">
            <h3 className="text-sm font-semibold text-on-surface">缺失素材列表</h3>
          </div>
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
            {!items.length && (
              <div className="p-8 text-center text-on-surface-variant text-sm">当前暂无缺口项</div>
            )}
            {items.map((gap) => {
              const st = statusConfig[gap.status] || statusConfig.pending
              return (
                <div key={gap.id} onClick={() => setSelectedGapId(gap.id)} className={`p-4 rounded-lg cursor-pointer transition-all border-l-4 ${
                  selectedGap?.id === gap.id ? 'bg-primary/5 border-primary' : 'bg-surface-container-low border-transparent hover:bg-surface-container'
                }`}>
                  <div className="flex items-start gap-3">
                    <span className={`material-symbols-outlined ${st.color}`} style={{ fontVariationSettings: "'FILL' 1" }}>{st.icon}</span>
                    <div className="flex-1">
                      <div className="text-xs text-outline mb-1">{gap.section}</div>
                      <h4 className="text-sm font-semibold text-on-surface">{gap.title}</h4>
                      {gap.desc && <p className="text-xs text-on-surface-variant mt-1">{gap.desc}</p>}
                      <div className="mt-2 flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1 text-xs font-medium ${st.color}`}>
                          <span className="w-1.5 h-1.5 rounded-full bg-current"></span>
                          {st.label}
                        </span>
                        {gap.status === 'skipped' && gap.skipReason && (
                          <span className="text-xs text-outline">原因: {gap.skipReason}</span>
                        )}
                        {gap.status === 'resolved' && gap.resolvedSource && (
                          <span className="text-xs text-outline">来源: {gap.resolvedSource}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          {selectedGap ? (
            <div className="p-6 flex-1 flex flex-col gap-6">
              <div>
                <h2 className="text-2xl font-headline font-bold text-on-surface mb-2">{selectedGap.title}</h2>
                <p className="text-sm text-on-surface-variant leading-relaxed">{selectedGap.desc || '请上传缺失素材并提交补录。'}</p>
                <p className="text-xs text-outline mt-2">归档标书类型：{selectedGap.bidType || detectBidType(selectedGap)}</p>
              </div>

              <div>
                <div className="flex justify-between items-center mb-3">
                  <h3 className="text-sm font-semibold text-on-surface">文件提交</h3>
                  <span className="text-xs text-outline">单次最多 5 个，单文件 500MB</span>
                </div>
                <div
                  className="border-2 border-dashed border-outline-variant rounded-xl p-10 flex flex-col items-center gap-3 hover:border-primary transition-colors cursor-pointer"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <span className="material-symbols-outlined text-4xl text-outline/50">cloud_upload</span>
                  <p className="text-sm text-on-surface-variant">点击上传缺失素材（生成补料回执）</p>
                  <p className="text-xs text-outline">支持 doc/docx/xls/xlsx/pdf/zip/png/jpg/jpeg/webp/bmp/tif/tiff</p>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  multiple
                  onChange={(event) => handleUploadChange(event)}
                />
              </div>

              <div className="rounded-xl border border-surface-container-high p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-on-surface">补料回执</h3>
                  {uploading && <span className="text-xs text-outline">提交中...</span>}
                </div>
                {!selectedGapSubmissions.length ? (
                  <p className="text-xs text-outline mt-3">暂无回执，请先上传文件。</p>
                ) : (
                  <div className="mt-3 space-y-2 max-h-44 overflow-auto pr-1">
                    {selectedGapSubmissions.map((item) => (
                      <div key={item.receiptId} className="rounded-lg bg-surface-container-low p-2 text-xs">
                        <div className="font-medium text-on-surface truncate">{item.fileName || item.fileId}</div>
                        <div className="text-outline mt-1 break-all">{item.storedPath || '-'}</div>
                        <div className="text-outline mt-1">{item.action === 'version' ? '生成版本' : '覆盖'} · {item.submittedAt || '-'}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3 mt-auto">
                <button onClick={openSkipDialog} disabled={savingGap} className="px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                  记录未补录原因
                </button>
                <button onClick={handleResolve} disabled={savingGap || !latestSubmission} className="px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">
                  <span className="material-symbols-outlined text-sm">check</span>
                  {savingGap ? '保存中...' : '确认补录'}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-outline">选择左侧缺口查看文件提交模块</div>
          )}
        </div>
      </div>

      {showSkipModal && (
        <div className="dialog-overlay" onClick={() => setShowSkipModal(false)}>
          <div className="dialog-content w-full max-w-lg animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
              <h3 className="text-lg font-headline font-bold text-on-surface">未补录原因</h3>
              <button onClick={() => setShowSkipModal(false)} className="text-on-surface-variant hover:text-primary transition-colors">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="p-6">
              <p className="text-sm text-on-surface-variant mb-3">请填写原因，该信息会进入 S6 审核视图。</p>
              <textarea
                value={skipReason}
                onChange={(e) => setSkipReason(e.target.value)}
                className="w-full h-28 px-4 py-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-2 focus:ring-primary/30 resize-none"
                placeholder="例如：该项在本项目不适用，已与业主确认。"
              />
            </div>
            <div className="px-6 py-4 border-t border-surface-container-high flex justify-end gap-3 bg-surface-container-low rounded-b-xl">
              <button onClick={() => setShowSkipModal(false)} className="px-4 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors">
                取消
              </button>
              <button
                onClick={handleSkip}
                disabled={savingGap || !skipReason.trim()}
                className="px-4 py-2 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {savingGap ? '保存中...' : '确认保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {conflictContext && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-surface-container-lowest rounded-xl border border-surface-container-high shadow-2xl">
            <div className="px-6 py-4 border-b border-surface-container-high">
              <h3 className="text-base font-semibold text-on-surface">文件命名冲突</h3>
            </div>
            <div className="p-6 text-sm text-on-surface-variant space-y-2">
              <p>目标目录已存在同名文件，请选择处理方式：</p>
              {conflictContext.detail?.path && (
                <p className="text-xs text-outline break-all">{conflictContext.detail.path}</p>
              )}
            </div>
            <div className="px-6 py-4 border-t border-surface-container-high bg-surface-container-low flex justify-end gap-2 rounded-b-xl">
              <button onClick={() => setConflictContext(null)} className="px-3 py-2 text-sm rounded-lg text-on-surface-variant hover:bg-surface-container-high">
                取消
              </button>
              <button
                onClick={() => resolveUploadConflict('overwrite')}
                className="px-3 py-2 text-sm rounded-lg border border-surface-container-high text-on-surface-variant hover:bg-surface-container-high"
              >
                覆盖
              </button>
              <button
                onClick={() => resolveUploadConflict('version')}
                className="px-3 py-2 text-sm rounded-lg bg-primary text-on-primary hover:bg-primary-container"
              >
                生成 v2
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
