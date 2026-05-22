import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { documentAPI } from '../../../api'
import { PageError, PageLoading } from '../components/TechnicalPageState'
import DataCard from '../components/TechnicalDataCard'
import ProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import StageGroupNav from '../components/TechnicalStageGroupNav'

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
      setError(e?.message || '最终文件加载失败')
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
  const fileName = data?.fileName || '投标文件_终版.docx'

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />
      <div className="rounded-lg border border-outline-variant/55 bg-surface-container-low px-5 py-4 shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
        <div className="flex flex-col gap-3.5 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-col gap-2.5 lg:flex-row lg:items-center">
            <StageGroupNav
              current="export"
              variant="compact"
              items={[
                { key: 'editor', label: '文档编辑', icon: 'edit_document', path: '/editor' },
                { key: 'export', label: '最终导出', icon: 'download', path: '/export' },
              ]}
            />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-base font-headline font-bold leading-tight text-on-surface">最终导出</h1>
                <span className="inline-flex h-6 items-center rounded-md bg-secondary-container px-2 text-xs font-semibold text-on-secondary-container">
                  可下载
                </span>
              </div>
              <p className="mt-1 truncate text-xs leading-relaxed text-on-surface-variant">
                核对最终版 Word 文件信息，并下载交付文档。
              </p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2.5 xl:justify-end">
            <a
              href={downloadUrl}
              download={fileName}
              onClick={() => showToast?.('开始下载最终版文档')}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3.5 text-xs font-semibold text-on-primary transition-colors hover:bg-primary-container hover:text-on-primary-container"
            >
              <span className="material-symbols-outlined text-[16px] leading-none">download</span>
              下载最终版 Word
            </a>
          </div>
        </div>
        <div className="mt-3 grid gap-1.5 rounded-md bg-surface-container-lowest px-4 py-3 text-xs leading-relaxed text-on-surface-variant lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-4">
          <span className="whitespace-nowrap">文件类型：{(data?.fileType || 'docx').toUpperCase()}</span>
          <span className="truncate text-outline" title={fileName}>
            文件名：{fileName}
          </span>
          <span className="whitespace-nowrap text-outline">最近保存：{formatDateTime(data?.lastSavedAt)}</span>
        </div>
      </div>

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
              使用页面顶部的“下载最终版 Word”完成交付文件下载。
            </p>
          </div>
        </div>
      </DataCard>
    </div>
  )
}
