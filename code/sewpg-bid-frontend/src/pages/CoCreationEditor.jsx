import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { documentAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const formatDateTime = (value) => {
  if (!value) return '未保存'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未保存'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function CoCreationEditor({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [fallbackContent, setFallbackContent] = useState('')
  const [savingFallback, setSavingFallback] = useState(false)
  const [forceSaving, setForceSaving] = useState(false)
  const [finishingStage, setFinishingStage] = useState(false)

  const loadDocument = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await documentAPI.get(id)
      setData(payload)
      setFallbackContent(payload?.fallback?.content || '')
      setOnlyofficeError('')
    } catch (e) {
      setError(e?.message || 'S9 文档加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadDocument()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadDocument])

  const hasOnlyOfficeSession = Boolean(data?.onlyoffice?.fileUrl && data?.onlyoffice?.callbackUrl)
  const useFallbackEditor = !hasOnlyOfficeSession || Boolean(onlyofficeError)

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await documentAPI.save(id, { content })
      setData(response?.payload || data)
      showToast?.('文档已保存并回写')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const handleForceSave = async () => {
    setForceSaving(true)
    try {
      const response = await documentAPI.forceSave(id)
      setData(response?.payload || data)
      showToast?.('已刷新真实文档状态')
    } catch (e) {
      showToast?.(e?.message || '刷新文档状态失败', 'error')
    } finally {
      setForceSaving(false)
    }
  }

  const handleFinishS9 = async () => {
    setFinishingStage(true)
    try {
      await stagesAPI.update(id, 9, { status: 'completed' })
      showToast?.('S9 已完成，已进入 S10')
      navigate(projectRoute(id, '/export', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || 'S9 完成失败，请稍后重试', 'error')
    } finally {
      setFinishingStage(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S9 人机共创文档..." />
  if (error) return <PageError title="S9 文档加载失败" description={error} onRetry={loadDocument} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={loadDocument}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleFinishS9}
              disabled={finishingStage}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {finishingStage ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1 text-sm">
            <div className="text-on-surface">
              <span className="text-on-surface-variant">文件：</span>
              <span className="font-medium">{data?.fileName || '-'}</span>
            </div>
            <div className="text-on-surface">
              <span className="text-on-surface-variant">来源：</span>
              <span>{data?.sourceFileName || '-'}</span>
            </div>
          </div>
          <div className="flex flex-col gap-1 text-xs text-outline">
            <span>保存版本：v{data?.version || 1}</span>
            <span>最近保存：{formatDateTime(data?.lastSavedAt)}</span>
          </div>
        </div>

        <div className="p-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-on-surface-variant">
              {useFallbackEditor
                ? '当前未拿到可用的 OnlyOffice 会话，或编辑器初始化失败，已切换为文本编辑兜底模式。保存后同样会回写，不会丢失。'
                : 'OnlyOffice 在线编辑已启用。文档保存由真实 OnlyOffice 服务回写；如需同步最新保存时间与版本号，请点击“刷新文档状态”。'}
            </div>
            <button
              onClick={handleForceSave}
              disabled={forceSaving}
              className="stage-action-btn px-4 py-2 text-xs font-semibold rounded-lg bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {forceSaving ? '刷新中...' : '刷新文档状态'}
            </button>
          </div>

          {onlyofficeError && (
            <div className="rounded-lg border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
              {onlyofficeError}
            </div>
          )}

          <div className={useFallbackEditor ? 'hidden' : 'block'}>
            <div className="h-[78vh] min-h-[780px] rounded-xl border border-outline-variant bg-surface-container-low overflow-hidden">
              <OnlyOfficeEmbed
                session={data?.onlyoffice}
                className="w-full h-full border-0 bg-white"
                onReady={() => setOnlyofficeError('')}
                onError={(message) => setOnlyofficeError(message)}
              />
            </div>
          </div>

          <div className={useFallbackEditor ? 'flex flex-col gap-3' : 'hidden'}>
            <textarea
              value={fallbackContent}
              onChange={(event) => setFallbackContent(event.target.value)}
              className="w-full h-[75vh] min-h-[720px] rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            <div className="flex justify-end">
              <button
                onClick={handleSaveFallback}
                disabled={savingFallback}
                className="stage-action-btn px-4 py-2 text-sm font-semibold rounded-lg bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {savingFallback ? '保存中...' : '保存回写'}
              </button>
            </div>
          </div>
        </div>
      </DataCard>
    </div>
  )
}
