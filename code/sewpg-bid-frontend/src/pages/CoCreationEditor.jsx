import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { documentAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/shared/OnlyOfficeWorkspace'
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
      setError(e?.message || 'S5 共创文档加载失败')
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
  const editorModeLabel = useFallbackEditor ? '文本兜底' : 'OnlyOffice 在线编辑'

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

  const handleFinishCoCreation = async () => {
    setFinishingStage(true)
    try {
      await stagesAPI.update(id, 5, { status: 'completed' })
      showToast?.('S5 共创已完成，已进入 S6 导出')
      navigate(projectRoute(id, '/export', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || 'S5 共创完成失败，请稍后重试', 'error')
    } finally {
      setFinishingStage(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S5 人机共创文档..." />
  if (error) return <PageError title="S5 文档加载失败" description={error} onRetry={loadDocument} />

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
              onClick={handleFinishCoCreation}
              disabled={finishingStage}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {finishingStage ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <OnlyOfficeWorkspace
        heightClass="min-h-[780px]"
        gridClassName="xl:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]"
        documentTitle="共创文档"
        documentSubtitle={data?.fileName || '未生成文档'}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
            {editorModeLabel}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-surface-container-high bg-surface-container-low px-5 py-4">
              <h3 className="text-base font-semibold text-on-surface">文档上下文</h3>
              <p className="mt-1 truncate text-xs text-outline" title={data?.sourceFileName || '-'}>
                来源：{data?.sourceFileName || '-'}
              </p>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-xs text-on-surface-variant">文件名</div>
                  <div className="mt-1 break-words font-medium text-on-surface">{data?.fileName || '-'}</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md bg-surface-container-low px-3 py-2">
                    <div className="text-xs text-on-surface-variant">版本</div>
                    <div className="mt-1 font-semibold text-on-surface">v{data?.version || 1}</div>
                  </div>
                  <div className="rounded-md bg-surface-container-low px-3 py-2">
                    <div className="text-xs text-on-surface-variant">模式</div>
                    <div className="mt-1 font-semibold text-on-surface">{editorModeLabel}</div>
                  </div>
                </div>
                <div>
                  <div className="text-xs text-on-surface-variant">最近保存</div>
                  <div className="mt-1 text-on-surface">{formatDateTime(data?.lastSavedAt)}</div>
                </div>
              </div>

              {onlyofficeError && (
                <div className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
                  {onlyofficeError}
                </div>
              )}

              <button
                onClick={handleForceSave}
                disabled={forceSaving}
                className="flex h-8 w-full items-center justify-center rounded-md bg-primary px-3 text-xs font-semibold text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
              >
                {forceSaving ? '刷新中...' : '刷新文档状态'}
              </button>
            </div>
          </div>
        )}
      >
        <div className={useFallbackEditor ? 'hidden' : 'min-h-0 flex-1'}>
          <OnlyOfficeEmbed
            session={data?.onlyoffice}
            className="h-full min-h-[680px] w-full rounded-md border border-outline-variant bg-white"
            onReady={() => setOnlyofficeError('')}
            onError={(message) => setOnlyofficeError(message)}
          />
        </div>

        <div className={useFallbackEditor ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
          <textarea
            value={fallbackContent}
            onChange={(event) => setFallbackContent(event.target.value)}
            className="min-h-[620px] flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
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
      </OnlyOfficeWorkspace>
    </div>
  )
}
