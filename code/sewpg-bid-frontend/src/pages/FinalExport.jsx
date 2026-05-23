import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { documentAPI, projectsAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import Button from '../components/ui/Button'
import Toolbar from '../components/ui/Toolbar'

const formatDateTime = (value) => {
  if (!value) return '未保存'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未保存'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function FinalExport({ showToast }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, projectPayload] = await Promise.all([
        documentAPI.final(id),
        projectsAPI.get(id).catch(() => null),
      ])
      setData(payload)
      setProject(projectPayload)
    } catch (e) {
      setError(e?.message || '共创导出最终文件加载失败')
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

  if (loading) return <PageLoading title="正在加载最终文档..." />
  if (error) return <PageError title="最终文档加载失败" description={error} onRetry={loadData} />

  const downloadUrl = data?.fileUrl || '#'
  const bidLabel = String(project?.bidType || '').includes('商务') ? '商务标' : '技术标'
  const fileName = data?.fileName || `${bidLabel}投标文件_终版.docx`

  return (
    <div className="stage-page business-ui-shell flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <Toolbar>
            <Button type="button" onClick={loadData} size="stage" variant="quiet">
              刷新
            </Button>
            <Button
              as="a"
              href={downloadUrl}
              download={fileName}
              onClick={() => showToast?.(`开始下载${bidLabel}最终版 Word`)}
              size="stage"
              variant="primary"
            >
              下载 Word
            </Button>
          </Toolbar>
        )}
      />

      <DataCard className="!p-0 overflow-hidden business-panel min-h-[360px]">
        <div className="business-section-head flex items-center justify-between gap-3 border-b border-surface-container-high px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-headline font-bold text-on-surface">最终版文件</h3>
            <p className="mt-1 truncate text-xs text-outline" title={fileName}>{fileName}</p>
          </div>
          <span className="rounded-md bg-secondary-container px-2.5 py-1 text-xs font-semibold text-on-secondary-container">
            v{data?.version || 1}
          </span>
        </div>

        <div className="grid gap-4 bg-surface-container-low p-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(320px,0.5fr)]">
          <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
            <h4 className="text-sm font-semibold text-on-surface">文件信息</h4>
            <div className="mt-3 divide-y divide-surface-container-high text-sm">
              {[
                ['文件名', fileName],
                ['文件类型', String(data?.fileType || 'docx').toUpperCase()],
                ['最近保存', formatDateTime(data?.lastSavedAt)],
                ['版本号', `v${data?.version || 1}`],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-4 py-3">
                  <span className="text-on-surface-variant">{label}</span>
                  <span className="break-all text-right font-medium text-on-surface">{value}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="business-panel flex min-h-[220px] flex-col justify-between rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
            <div>
              <h4 className="text-sm font-semibold text-on-surface">下载</h4>
              <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
                下载当前共创后的最终版 Word 文档。
              </p>
            </div>
            <Button
              as="a"
              href={downloadUrl}
              download={fileName}
              onClick={() => showToast?.(`开始下载${bidLabel}最终版 Word`)}
              className="mt-6 w-full"
              size="lg"
              variant="primary"
            >
              下载最终版 Word
            </Button>
          </div>
        </div>
      </DataCard>
    </div>
  )
}
