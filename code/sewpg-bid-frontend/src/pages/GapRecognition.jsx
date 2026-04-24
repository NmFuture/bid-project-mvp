import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'

const formatDateTime = (value) => {
  if (!value) return '未识别'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未识别'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function GapRecognition({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [advancing, setAdvancing] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await gapsAPI.detectionStatus(id)
      setData(payload)
    } catch (e) {
      setError(e?.message || '素材缺口识别状态加载失败')
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

  const isCompleted = data?.status === 'completed'
  const missingItems = Array.isArray(data?.items) ? data.items : []

  const handleRunDetection = async () => {
    if (running) return
    setRunning(true)
    try {
      const payload = await gapsAPI.runDetection(id)
      setData(payload)
      showToast?.(payload?.message || '素材缺口识别完成')
    } catch (e) {
      showToast?.(e?.message || '触发识别失败，请稍后重试', 'error')
    } finally {
      setRunning(false)
    }
  }

  const handleGoNextStage = async () => {
    if (!isCompleted) {
      showToast?.('请先完成 S4 素材缺口识别后再进入 S5。', 'error')
      return
    }

    setAdvancing(true)
    try {
      await stagesAPI.update(id, 4, { status: 'completed' })
      showToast?.('已进入 S5 备料补交')
      navigate(`/projects/${id}/gaps-fill`)
    } catch (e) {
      showToast?.(e?.message || '进入 S5 失败，请稍后重试', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S4 素材缺口识别..." />
  if (error) return <PageError title="S4 素材缺口识别加载失败" description={error} onRetry={loadData} />

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
              onClick={handleRunDetection}
              disabled={running}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {running ? '识别中...' : isCompleted ? '重新识别' : '触发识别'}
            </button>
            <button
              onClick={handleGoNextStage}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '识别完成后可进入 S5' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {advancing ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[420px]">
        <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between bg-surface-container-low">
          <h3 className="text-sm font-semibold text-on-surface">缺失素材清单</h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-outline">识别时间：{formatDateTime(data?.recognizedAt)}</span>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${isCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
              {isCompleted ? '识别完成' : '待识别'}
            </span>
          </div>
        </div>

        {!isCompleted ? (
          <div className="h-[340px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">fact_check</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">S4 待识别</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              点击“触发识别”后，系统会根据 S1/S2 结果识别缺失素材并生成补料清单。
            </p>
            <button
              onClick={handleRunDetection}
              disabled={running}
              className="stage-action-btn mt-6 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {running ? '识别中...' : '触发识别'}
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-container-low border-b border-surface-container-high">
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">缺失素材</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">所属章节</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">补充说明</th>
                </tr>
              </thead>
              <tbody>
                {missingItems.map((item) => (
                  <tr key={item.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                    <td className="px-6 py-3 text-on-surface font-medium min-w-[220px]">{item.title}</td>
                    <td className="px-6 py-3 text-on-surface-variant min-w-[200px]">{item.section}</td>
                    <td className="px-6 py-3 text-on-surface-variant min-w-[320px]">{item.desc || '请尽快补齐该项素材。'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DataCard>
    </div>
  )
}
