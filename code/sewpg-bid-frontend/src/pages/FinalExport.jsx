import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { documentAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

const formatDateTime = (value) => {
  if (!value) return '未保存'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未保存'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function FinalExport({ showToast }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await documentAPI.final(id)
      setData(payload)
    } catch (e) {
      setError(e?.message || 'S10 最终文件加载失败')
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

  if (loading) return <PageLoading title="正在加载 S10 最终文档..." />
  if (error) return <PageError title="S10 最终文档加载失败" description={error} onRetry={loadData} />

  const downloadUrl = data?.fileUrl || '#'
  const fileName = data?.fileName || 'S9_终版.docx'

  return (
    <div className="flex flex-col gap-6 animate-fade-in max-w-6xl mx-auto w-full">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        title="S10 导出"
        description="本阶段仅提供 S9 最终版 Word 文件下载。"
        actions={(
          <button
            onClick={loadData}
            className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            刷新
          </button>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[320px]">
        <div className="px-6 py-5 border-b border-surface-container-high bg-surface-container-low">
          <h2 className="text-lg font-headline font-bold text-on-surface">S9 最终版文档</h2>
          <p className="text-sm text-on-surface-variant mt-1">下载前请确认 S9 文档已保存回写。</p>
        </div>

        <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
            <h3 className="text-sm font-semibold text-on-surface mb-3">文件信息</h3>
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-on-surface-variant">文件名</span>
                <span className="text-on-surface font-medium text-right">{fileName}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-on-surface-variant">文件类型</span>
                <span className="text-on-surface font-medium uppercase">{data?.fileType || 'docx'}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-on-surface-variant">最近保存</span>
                <span className="text-on-surface font-medium">{formatDateTime(data?.lastSavedAt)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-on-surface-variant">版本号</span>
                <span className="text-on-surface font-medium">v{data?.version || 1}</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-semibold text-on-surface mb-2">下载</h3>
              <p className="text-sm text-on-surface-variant">
                点击下方按钮下载 S9 最终版 Word 文档。
              </p>
            </div>
            <a
              href={downloadUrl}
              download={fileName}
              onClick={() => showToast?.('开始下载 S9 最终版文档')}
              className="mt-6 inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors"
            >
              <span className="material-symbols-outlined text-sm">download</span>
              下载最终版 Word
            </a>
          </div>
        </div>
      </DataCard>
    </div>
  )
}
