import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI, generateAPI, materialsAPI, reviewAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const formatDateTime = (value) => {
  if (!value) return '未执行'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未执行'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const statusConfig = {
  matched: { label: '已匹配', tone: 'bg-secondary-container text-on-secondary-container', icon: 'check_circle' },
  structural: { label: '结构章节', tone: 'bg-surface-container-high text-on-surface-variant', icon: 'account_tree' },
  missing: { label: '缺素材', tone: 'bg-error/10 text-error', icon: 'error' },
  needs_input: { label: '需处理', tone: 'bg-tertiary-fixed text-on-tertiary-fixed', icon: 'edit_note' },
  filling: { label: '处理中', tone: 'bg-primary/10 text-primary', icon: 'pending' },
  resolved: { label: '已解决', tone: 'bg-secondary-container text-on-secondary-container', icon: 'task_alt' },
  ignored: { label: '已忽略', tone: 'bg-surface-container-high text-on-surface-variant', icon: 'do_not_disturb_on' },
}

const normalizeItems = (payload) => {
  const planItems = payload?.gapPlan?.items
  if (Array.isArray(planItems) && planItems.length) return planItems
  return (Array.isArray(payload?.items) ? payload.items : []).map((item) => ({
    id: item.id,
    number: '',
    title: item.title,
    section: item.section,
    status: item.status === 'resolved' ? 'resolved' : item.status === 'skipped' ? 'ignored' : 'missing',
    gapReason: item.desc,
    matchedMaterials: [],
    fillTasks: [],
    resolvedArtifacts: [],
    reviewNotes: [],
  }))
}

const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result || ''))
  reader.onerror = () => reject(reader.error || new Error('文件读取失败'))
  reader.readAsDataURL(file)
})

export default function GapRecognition({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [materialKeyword, setMaterialKeyword] = useState('')
  const [materialSearch, setMaterialSearch] = useState({ items: [], total: 0 })
  const [materialLoading, setMaterialLoading] = useState(false)
  const [selectedMaterialIds, setSelectedMaterialIds] = useState([])
  const fileInputRef = useRef(null)

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const payload = await gapsAPI.detectionStatus(id)
      const items = normalizeItems(payload)
      setData(payload)
      setSelectedId((prev) => (items.some((item) => item.id === prev) ? prev : items[0]?.id || ''))
    } catch (e) {
      if (!silent) setError(e?.message || '缺口识别与处理加载失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const items = useMemo(() => normalizeItems(data), [data])
  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) || items[0] || null,
    [items, selectedId],
  )
  const selectedMaterialItems = useMemo(
    () => materialSearch.items.filter((item) => selectedMaterialIds.includes(item.id)),
    [materialSearch.items, selectedMaterialIds],
  )
  const summary = data?.gapPlan?.summary || data?.summary || {}
  const integrity = data?.gapPlan?.integrity || data?.integrity || {}
  const isCompleted = data?.status === 'completed'
  const canGenerate = isCompleted && (integrity?.status === 'passed' || Number(summary?.blockingCount || 0) === 0)

  const updatePayload = (payload) => {
    const next = payload?.payload || payload
    setData(next)
    const nextItems = normalizeItems(next)
    setSelectedId((prev) => (nextItems.some((item) => item.id === prev) ? prev : nextItems[0]?.id || ''))
  }

  const runAction = async (key, fn, success) => {
    if (busyAction) return
    setBusyAction(key)
    try {
      const payload = await fn()
      if (payload) updatePayload(payload)
      if (success) showToast?.(success(payload))
    } catch (e) {
      showToast?.(e?.message || '操作失败，请稍后重试', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const handleRunDetection = () => runAction(
    'detect',
    () => gapsAPI.runDetection(id),
    (payload) => payload?.message || '缺口识别完成',
  )

  const handleSearchMaterials = async () => {
    setMaterialLoading(true)
    try {
      const payload = await materialsAPI.raw.files({
        keyword: materialKeyword,
        bidType: '技术标',
        pageSize: 12,
        recursive: true,
      })
      setMaterialSearch({
        items: Array.isArray(payload?.items) ? payload.items : [],
        total: Number(payload?.total || 0),
      })
      setSelectedMaterialIds((prev) => prev.filter((id) => (payload?.items || []).some((item) => item.id === id)))
    } catch (e) {
      showToast?.(e?.message || '查询素材失败', 'error')
    } finally {
      setMaterialLoading(false)
    }
  }

  const toggleMaterial = (materialId) => {
    setSelectedMaterialIds((prev) => (
      prev.includes(materialId)
        ? prev.filter((item) => item !== materialId)
        : [...prev, materialId]
    ))
  }

  const handleSelectMaterials = () => {
    if (!selected || !selectedMaterialItems.length) {
      showToast?.('请先选择素材。', 'error')
      return
    }
    return runAction(
      `select-${selected.id}`,
      () => gapsAPI.selectMaterial(id, selected.id, {
        materials: selectedMaterialItems.map((item) => ({
          id: item.id,
          name: item.name,
          folderPath: item.folderPath,
          materialTier: item.materialTier,
          cleanedFileName: item.cleanedFileName,
        })),
      }),
      () => '已选择已有素材并挂回缺口计划。',
    )
  }

  const handleAiFill = () => {
    if (!selected?.fillTasks?.length) {
      showToast?.('当前目录项没有可执行的 AI 填写任务。', 'error')
      return
    }
    const task = selected.fillTasks[0]
    return runAction(
      `ai-${selected.id}`,
      () => gapsAPI.aiFill(id, selected.id, {
        fillTaskId: task.id,
        referenceMaterialIds: selectedMaterialIds.length
          ? selectedMaterialIds
          : (selected.matchedMaterials || []).map((item) => item.id).filter(Boolean),
        parseFieldIds: [task.blankSource?.id].filter(Boolean),
      }),
      () => 'AI 填写完成，产物已挂回缺口计划。',
    )
  }

  const handleIgnore = () => {
    if (!selected) return
    return runAction(
      `ignore-${selected.id}`,
      () => gapsAPI.updateMissing(id, selected.id, { status: 'skipped', reason: '人工确认本项目不适用或无需补充。' }),
      () => '已记录人工忽略原因。',
    )
  }

  const handleUploadPicked = async (event) => {
    const files = Array.from(event.target.files || [])
    if (event.target) event.target.value = ''
    if (!selected || !files.length) return
    if (busyAction) return
    setBusyAction(`upload-${selected.id}`)
    try {
      const payload = await gapsAPI.upload(id, selected.id, {
        bidType: '技术标',
        files: await Promise.all(files.map(async (file) => ({
          name: file.name,
          type: file.type || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          size: Number(file.size || 0),
          data: await readFileAsDataUrl(file),
        }))),
      })
      updatePayload(payload)
      showToast?.('客户资料已上传并挂回缺口计划。')
    } catch (e) {
      showToast?.(e?.message || '上传客户资料失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const handleRecheck = () => runAction(
    'recheck',
    async () => {
      await gapsAPI.recheck(id)
      return gapsAPI.detectionStatus(id)
    },
    () => '缺口完整性校验完成。',
  )

  const handleSubmitAndGenerate = () => runAction(
    'generate',
    async () => {
      await gapsAPI.submitReview(id)
      await reviewAPI.prepareParse(id)
      await reviewAPI.confirm(id)
      await stagesAPI.update(id, 3, { status: 'completed' })
      const started = await generateAPI.run(id)
      navigate(projectRoute(id, '/generate', workspaceSlug))
      return started
    },
    (payload) => payload?.message || '已通过缺口校验并开始生成标书。',
  )

  if (loading) return <PageLoading title="正在加载 S3 缺口处理..." />
  if (error) return <PageError title="S3 缺口处理加载失败" description={error} onRetry={loadData} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb currentLabel="S3 缺口处理" />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={() => loadData()}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleRunDetection}
              disabled={Boolean(busyAction)}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'detect' ? '识别中...' : isCompleted ? '重新识别缺口' : '识别缺口'}
            </button>
            <button
              onClick={handleRecheck}
              disabled={!isCompleted || Boolean(busyAction)}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'recheck' ? '检查中...' : '重新检查缺口'}
            </button>
            <button
              onClick={handleSubmitAndGenerate}
              disabled={!canGenerate || Boolean(busyAction)}
              title={!canGenerate ? '全部缺口解决后可生成标书' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'generate' ? '提交中...' : '生成标书'}
            </button>
          </>
        )}
      />

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {[
          ['目录项', summary.totalTocItems ?? items.length],
          ['已匹配', summary.matchedCount ?? 0],
          ['缺口', summary.missingCount ?? 0],
          ['已解决', summary.resolvedCount ?? 0],
          ['AI 填写任务', summary.fillableTaskCount ?? 0],
        ].map(([label, value]) => (
          <DataCard key={label} className="!p-4">
            <div className="text-xs text-on-surface-variant">{label}</div>
            <div className="mt-1 text-2xl font-headline font-bold text-on-surface">{value}</div>
          </DataCard>
        ))}
      </div>

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-surface-container-low">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">匹配/缺口处理计划</h3>
            <p className="text-xs text-on-surface-variant mt-1">
              识别时间：{formatDateTime(data?.recognizedAt)} · 校验状态：{integrity?.status === 'passed' ? '已通过' : '未通过或待检查'}
            </p>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${isCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {isCompleted ? '计划已生成' : '待识别'}
          </span>
        </div>

        {!isCompleted ? (
          <div className="h-[340px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">fact_check</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">等待生成缺口计划</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              点击“识别缺口”后会调用缺口识别 Skill，按已确认目录、素材库 Wiki、真实素材和解析结果生成处理计划。
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-12 min-h-[560px]">
            <div className="xl:col-span-7 border-r border-surface-container-high overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface-container-low border-b border-surface-container-high">
                    <th className="px-5 py-3 text-left font-semibold text-on-surface">目录项</th>
                    <th className="px-5 py-3 text-left font-semibold text-on-surface">状态</th>
                    <th className="px-5 py-3 text-left font-semibold text-on-surface">素材/任务</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const cfg = statusConfig[item.status] || statusConfig.missing
                    return (
                      <tr
                        key={item.id}
                        onClick={() => {
                          setSelectedId(item.id)
                          setSelectedMaterialIds([])
                        }}
                        className={`border-b border-surface-container-high cursor-pointer hover:bg-surface-container-low/60 ${selected?.id === item.id ? 'bg-primary/5' : ''}`}
                      >
                        <td className="px-5 py-3 min-w-[280px]">
                          <div className="text-xs text-outline">{item.number || item.section || '-'}</div>
                          <div className="font-medium text-on-surface mt-1">{item.title}</div>
                          {item.gapReason ? <div className="text-xs text-on-surface-variant mt-1">{item.gapReason}</div> : null}
                        </td>
                        <td className="px-5 py-3 min-w-[120px]">
                          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-semibold ${cfg.tone}`}>
                            <span className="material-symbols-outlined text-[16px]">{cfg.icon}</span>
                            {cfg.label}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-on-surface-variant min-w-[240px]">
                          <div>{(item.matchedMaterials || []).length} 份匹配素材</div>
                          <div>{(item.fillTasks || []).length} 个 AI 填写任务</div>
                          <div>{(item.resolvedArtifacts || []).length} 个解决产物</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <div className="xl:col-span-5 p-5 bg-surface-container-lowest">
              {selected ? (
                <div className="flex flex-col gap-5">
                  <div>
                    <div className="text-xs text-outline">{selected.number || selected.section || '-'}</div>
                    <h3 className="mt-1 text-xl font-headline font-bold text-on-surface">{selected.title}</h3>
                    <p className="text-sm text-on-surface-variant mt-2">{selected.gapReason || selected.reason || '当前目录项已纳入缺口处理计划。'}</p>
                  </div>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">匹配素材</h4>
                    {(selected.matchedMaterials || []).length ? (
                      <div className="space-y-2">
                        {selected.matchedMaterials.map((item, index) => (
                          <div key={`${item.id || item.path}-${index}`} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{item.id || item.path || '素材'}</div>
                            <div className="text-outline break-all mt-1">{item.path || item.docx || item.matchReason || '-'}</div>
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">暂无匹配素材。</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h4 className="text-sm font-semibold text-on-surface">选择已有素材</h4>
                      <button
                        onClick={handleSelectMaterials}
                        disabled={!selectedMaterialItems.length || Boolean(busyAction)}
                        className="h-8 px-3 bg-secondary text-on-secondary text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `select-${selected.id}` ? '挂回中...' : '挂回缺口'}
                      </button>
                    </div>
                    <div className="flex gap-2">
                      <input
                        value={materialKeyword}
                        onChange={(event) => setMaterialKeyword(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') handleSearchMaterials()
                        }}
                        placeholder="搜索素材名称"
                        className="min-w-0 flex-1 h-9 px-3 rounded-md border border-surface-container-high bg-surface text-sm text-on-surface"
                      />
                      <button
                        onClick={handleSearchMaterials}
                        disabled={materialLoading}
                        className="h-9 px-3 bg-surface-container-high text-on-surface-variant text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {materialLoading ? '查询中...' : '查询'}
                      </button>
                    </div>
                    <div className="mt-3 space-y-2 max-h-44 overflow-y-auto">
                      {materialSearch.items.length ? materialSearch.items.map((item) => {
                        const checked = selectedMaterialIds.includes(item.id)
                        return (
                          <label key={item.id} className="flex items-start gap-2 rounded-md bg-surface-container-low px-3 py-2 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleMaterial(item.id)}
                              className="mt-0.5"
                            />
                            <span className="min-w-0">
                              <span className="block font-medium text-on-surface">{item.name}</span>
                              <span className="block text-outline break-all mt-1">
                                {item.id} · {item.hasCleanedWord ? '清洗稿' : '原始 Word'} · {item.folderPath || '-'}
                              </span>
                            </span>
                          </label>
                        )
                      }) : (
                        <p className="text-xs text-outline">
                          {materialLoading ? '正在查询素材...' : '输入关键词后查询素材库，可作为缺口解决产物或 AI 填写参考。'}
                        </p>
                      )}
                    </div>
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h4 className="text-sm font-semibold text-on-surface">AI 填写任务</h4>
                      <button
                        onClick={handleAiFill}
                        disabled={!selected.fillTasks?.length || Boolean(busyAction)}
                        className="h-8 px-3 bg-primary text-on-primary text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `ai-${selected.id}` ? '填写中...' : '调用 Skill 填写'}
                      </button>
                    </div>
                    {(selected.fillTasks || []).length ? (
                      <div className="space-y-2">
                        {selected.fillTasks.map((task) => (
                          <div key={task.id} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{task.title || task.id}</div>
                            <div className="text-outline mt-1">Skill：{task.skill} · 状态：{task.status || 'pending'}</div>
                            {task.blankSource?.title ? <div className="text-outline mt-1">空表：{task.blankSource.title}</div> : null}
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">当前目录项不需要 AI 填写。</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-semibold text-on-surface">客户资料上传</h4>
                        <p className="text-xs text-outline mt-1">上传后会作为项目补料产物挂回当前目录项。</p>
                      </div>
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={Boolean(busyAction)}
                        className="h-8 px-3 bg-surface-container-high text-on-surface-variant text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `upload-${selected.id}` ? '上传中...' : '上传资料'}
                      </button>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="hidden"
                      multiple
                      onChange={handleUploadPicked}
                    />
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">处理产物</h4>
                    {(selected.resolvedArtifacts || []).length ? (
                      <div className="space-y-2">
                        {selected.resolvedArtifacts.map((artifact) => (
                          <div key={artifact.id} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{artifact.fileName || artifact.title || artifact.id}</div>
                            <div className="text-outline mt-1">来源：{artifact.source || '-'} · Skill：{artifact.skill || '-'}</div>
                            {artifact.onlyoffice?.fileUrl ? (
                              <a className="inline-flex mt-2 text-primary font-semibold" href={artifact.onlyoffice.fileUrl} target="_blank" rel="noreferrer">
                                OnlyOffice 预览
                              </a>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">暂无处理产物。</p>}
                  </section>

                  <div className="flex justify-end">
                    <button
                      onClick={handleIgnore}
                      disabled={Boolean(busyAction)}
                      className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      人工忽略
                    </button>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-outline">选择一个目录项查看处理详情</div>
              )}
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
