import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI } from '../../../api'
import DataCard from '../components/TechnicalDataCard'
import { PageError, PageLoading } from '../components/TechnicalPageState'
import ProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import { asObjectArray } from '../../../pages/gapRecognitionHelpers'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

const factStatusLabels = {
  empty: '待生成',
  draft: '待确认',
  confirmed: '已确认',
  candidate: '候选',
  missing: '待补充',
  conflict: '冲突',
}

const statusToneClass = (status = '') => {
  if (status === 'confirmed') return 'bg-secondary-container text-on-secondary-container'
  if (status === 'missing') return 'bg-tertiary-fixed text-on-tertiary-fixed'
  if (status === 'conflict') return 'bg-error/10 text-error'
  return 'bg-surface-container-high text-on-surface-variant'
}

const emptyFactTable = (projectId) => ({
  schemaVersion: 'bid-project-fact-table-v1',
  projectId,
  status: 'empty',
  fields: [],
  summary: {
    totalCount: 0,
    confirmedCount: 0,
    candidateCount: 0,
    missingCount: 0,
    conflictCount: 0,
  },
})

export default function TechnicalFactTable({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [factTable, setFactTable] = useState(() => emptyFactTable(id))
  const [factFields, setFactFields] = useState([])
  const [gapReady, setGapReady] = useState(false)

  const applyFactPayload = useCallback((payload) => {
    const next = payload?.schemaVersion ? payload : emptyFactTable(id)
    setFactTable(next)
    setFactFields(asObjectArray(next.fields))
  }, [id])

  const ensureGapPlan = useCallback(async () => {
    const statusPayload = await gapsAPI.detectionStatus(id)
    if (statusPayload?.status === 'completed') {
      setGapReady(true)
      return statusPayload
    }
    const generated = await gapsAPI.runDetection(id)
    setGapReady(true)
    return generated
  }, [id])

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const statusPayload = await gapsAPI.detectionStatus(id)
      const ready = statusPayload?.status === 'completed'
      setGapReady(ready)
      if (ready) {
        const facts = await gapsAPI.facts(id)
        applyFactPayload(facts)
      } else {
        applyFactPayload(emptyFactTable(id))
      }
    } catch (e) {
      setError(e?.message || '事实表加载失败')
    } finally {
      setLoading(false)
    }
  }, [applyFactPayload, id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const buildFacts = async () => {
    if (busyAction) return null
    setBusyAction('build')
    try {
      await ensureGapPlan()
      const payload = await gapsAPI.buildFacts(id)
      applyFactPayload(payload)
      showToast?.('项目事实表已生成')
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表生成失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const handleFieldChange = (index, key, value) => {
    setFactFields((current) => current.map((field, idx) => {
      if (idx !== index) return field
      const nextValue = key === 'value' ? value : field.value
      return {
        ...field,
        [key]: value,
        status: String(nextValue || '').trim()
          ? (field.status === 'confirmed' ? 'confirmed' : 'candidate')
          : 'missing',
      }
    }))
  }

  const addManualField = () => {
    const createdAt = new Date().toISOString()
    setFactFields((current) => [
      ...current,
      {
        id: `FACT-MANUAL-${Date.now()}`,
        key: '',
        label: '',
        category: '人工补充事实',
        value: '',
        unit: '',
        required: false,
        status: 'missing',
        confidence: 1,
        sourcePriority: 360,
        sourceRefs: [{ type: 'manualFact', title: '人工新增', field: '' }],
        alternatives: [],
        notes: 'S2.5 人工补充',
        updatedAt: createdAt,
        updatedBy: '当前用户',
      },
    ])
  }

  const confirmFacts = async () => {
    if (busyAction) return null
    const hasUnnamedManualValue = factFields.some((field) => {
      const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
      return isManualField && String(field.value || '').trim() && !String(field.label || '').trim()
    })
    if (hasUnnamedManualValue) {
      showToast?.('请先填写人工新增字段的字段名称', 'error')
      return null
    }
    let fields = factFields.filter((field) => String(field.label || field.value || '').trim())
    setBusyAction('confirm')
    try {
      if (!fields.length) {
        await ensureGapPlan()
        const built = await gapsAPI.buildFacts(id)
        fields = asObjectArray(built?.fields)
        applyFactPayload(built)
      }
      const payload = await gapsAPI.saveFacts(id, {
        fields,
        confirm: true,
        operator: '当前用户',
      })
      applyFactPayload(payload)
      showToast?.('项目事实表已确认，已进入素材匹配')
      navigate(projectRoute(id, '/gaps', workspaceSlug))
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表确认失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  if (loading) return <PageLoading title="正在加载项目事实表..." />
  if (error) return <PageError title="项目事实表加载失败" description={error} onRetry={loadData} />

  const summary = factTable?.summary || {}
  const status = factTable?.status || 'empty'

  return (
    <div className="stage-page flex w-full max-w-none animate-fade-in flex-col gap-6">
      <StageBreadcrumb currentLabel="事实表" />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <DataCard className="!p-0 overflow-hidden">
        <div className="border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-headline font-bold text-on-surface">项目事实表</h2>
                <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${statusToneClass(status)}`}>
                  {factStatusLabels[status] || status}
                </span>
                {!gapReady ? (
                  <span className="rounded-md bg-tertiary-fixed px-2.5 py-1 text-xs font-semibold text-on-tertiary-fixed">
                    待生成素材匹配计划
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-on-surface-variant">
                字段：{summary.totalCount || factFields.length || 0} · 已确认：{summary.confirmedCount || 0} · 待补充：{summary.missingCount || 0} · 冲突：{summary.conflictCount || 0}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={buildFacts}
                disabled={Boolean(busyAction)}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-surface-container-high px-3 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[16px]">rule_settings</span>
                {busyAction === 'build' ? '生成中...' : factFields.length ? '重新生成事实表' : '生成事实表'}
              </button>
              <button
                type="button"
                onClick={addManualField}
                disabled={Boolean(busyAction)}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-surface-container-high px-3 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[16px]">add</span>
                新增字段
              </button>
              <button
                type="button"
                onClick={confirmFacts}
                disabled={Boolean(busyAction)}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3.5 text-xs font-semibold text-on-primary hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[16px]">fact_check</span>
                {busyAction === 'confirm' ? '确认中...' : '确认事实表并进入素材匹配'}
              </button>
            </div>
          </div>
        </div>

        <div className="p-5">
          {factFields.length ? (
            <div className="overflow-hidden rounded-md border border-surface-container-high">
              <table className="w-full min-w-[920px] border-collapse bg-surface-container-lowest text-sm">
                <thead className="bg-surface-container-low text-left text-xs text-outline">
                  <tr>
                    <th className="w-44 px-3 py-2 font-semibold">字段</th>
                    <th className="w-72 px-3 py-2 font-semibold">确认值</th>
                    <th className="w-24 px-3 py-2 font-semibold">状态</th>
                    <th className="w-28 px-3 py-2 font-semibold">置信度</th>
                    <th className="px-3 py-2 font-semibold">来源素材/依据</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-high">
                  {factFields.map((field, index) => {
                    const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
                    const refs = asObjectArray(field.sourceRefs).slice(0, 2)
                    return (
                      <tr key={field.id || `${field.label}-${index}`} className="align-top">
                        <td className="px-3 py-2">
                          {isManualField ? (
                            <input
                              value={field.label || ''}
                              onChange={(event) => handleFieldChange(index, 'label', event.target.value)}
                              placeholder="字段名称"
                              className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm font-semibold text-on-surface"
                            />
                          ) : (
                            <div className="font-semibold text-on-surface">{field.label}</div>
                          )}
                          <div className="mt-1 text-[11px] text-outline">{field.category || '项目事实'}</div>
                        </td>
                        <td className="px-3 py-2">
                          <input
                            value={field.value || ''}
                            onChange={(event) => handleFieldChange(index, 'value', event.target.value)}
                            className={`h-9 w-full rounded-md border px-2 text-sm text-on-surface ${
                              field.status === 'missing'
                                ? 'border-tertiary bg-tertiary-fixed/40'
                                : 'border-surface-container-high bg-white'
                            }`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <span className={`inline-flex rounded-md px-2 py-1 text-[11px] font-semibold ${statusToneClass(field.status)}`}>
                            {factStatusLabels[field.status] || field.status || '-'}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {field.confidence ? `${Math.round(Number(field.confidence) * 100)}%` : '-'}
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {refs.length ? refs.map((ref) => (
                            <div key={`${ref.type || ''}-${ref.field || ref.title || ''}`} className="mb-1 truncate" title={[ref.title, ref.field, ref.gapId].filter(Boolean).join(' · ')}>
                              {[ref.title, ref.field, ref.gapId].filter(Boolean).join(' · ')}
                            </div>
                          )) : '-'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex min-h-[320px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest text-center">
              <div>
                <span className="material-symbols-outlined text-5xl text-primary">fact_check</span>
                <h3 className="mt-3 text-base font-semibold text-on-surface">还没有项目事实表</h3>
                <p className="mt-1 max-w-lg text-sm text-on-surface-variant">
                  先生成事实表，系统会基于项目信息、目录、素材和解析字段形成可人工确认的项目字段。
                </p>
              </div>
            </div>
          )}
        </div>
      </DataCard>
    </div>
  )
}
