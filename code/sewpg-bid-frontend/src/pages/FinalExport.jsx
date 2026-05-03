import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { documentAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'

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
      setError(e?.message || 'S6 最终文件加载失败')
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

  if (loading) return <PageLoading title="正在加载 S6 最终文档..." />
  if (error) return <PageError title="S6 最终文档加载失败" description={error} onRetry={loadData} />

  const downloadUrl = data?.fileUrl || '#'
  const fileName = data?.fileName || '投标文件_终版.docx'

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <button
            onClick={loadData}
            className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
          >
            刷新
          </button>
        )}
      />

      <DataCard className="!p-0 !bg-transparent !border-0 !shadow-none min-h-[320px]">
        <div className="p-0 mt-4 flex justify-center">
          <div className="w-full max-w-[46rem] rounded-lg border border-surface-container-high bg-surface-container-low p-4 flex flex-col gap-5">
            <h3 className="text-sm font-semibold text-on-surface">文件信息与下载</h3>
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
            <p className="text-sm text-on-surface-variant">
              点击下方按钮下载最终版 Word 文档。
            </p>
            <a
              href={downloadUrl}
              download={fileName}
              onClick={() => showToast?.('开始下载最终版文档')}
              className="stage-action-btn inline-flex items-center justify-center px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors"
            >
              下载最终版 Word
            </a>
          </div>
        </div>
      </DataCard>
    </div>
  )
}
