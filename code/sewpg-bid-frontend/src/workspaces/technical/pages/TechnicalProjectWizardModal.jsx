import { useEffect, useMemo, useState } from 'react'
import { technicalMaterialsAPI, technicalProjectInfoOptionsAPI, technicalProjectsAPI } from '../../../api'
import Button from '../../../components/ui/Button'
import {
  STATIC_FOUNDATION_TYPE_OPTIONS,
  STATIC_PROJECT_INFO_OPTIONS,
  OTHER_OPTION_LABEL,
  deriveCustomerOptionsFromIndex,
  deriveTurbineModelOptionsFromIndex,
  loadProjectInfoOptions,
} from '../../shared/projectInfoOptions'
import {
  buildPrimaryTurbineModel,
  cleanTurbineModelRows,
  createTurbineModelRow,
  isPositiveIntegerText,
  mergeOptionValues,
  normalizeTurbineModelRows,
} from '../../shared/projectInfoForm'
import {
  buildTechnicalProjectInitialForm,
  TECHNICAL_BID_TYPE,
} from '../technicalProjectPrefill'

const TECHNICAL_PROJECT_WIZARD_DRAFT_VERSION = 2
const TECHNICAL_PROJECT_WIZARD_DRAFT_PREFIX = 'sewpg.technicalProjectWizardDraft'
const FORM_REQUIRED_STEP = 0

const normalizeMaterialProjects = (list = []) =>
  (Array.isArray(list) ? list : [])
    .map((item) => ({
      id: String(item?.projectId || item?.id || '').trim(),
      projectId: String(item?.projectId || item?.id || '').trim(),
      projectCode: String(item?.projectCode || item?.projectId || item?.id || '').trim(),
      name: String(item?.projectName || item?.name || item?.projectCode || item?.projectId || item?.id || '').trim(),
      customerId: String(item?.customerId || '').trim(),
      customerName: String(item?.customerCanonicalName || item?.customerName || '').trim(),
      bidType: String(item?.bidType || '').trim(),
    }))
    .filter((item) => item.id && item.name)

const buildDraftKey = ({ mode = 'create', project = null, defaultBidType = '' }) => [
  TECHNICAL_PROJECT_WIZARD_DRAFT_PREFIX,
  mode,
  project?.id || 'new',
  project?.bidType || defaultBidType || 'unknown',
].join(':')

const readDraft = (key) => {
  if (typeof window === 'undefined' || !key) return null
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || 'null')
    if (!parsed || parsed.version !== TECHNICAL_PROJECT_WIZARD_DRAFT_VERSION || !parsed.form) return null
    return {
      ...parsed,
      step: FORM_REQUIRED_STEP,
      form: {
        ...parsed.form,
        turbineModels: Array.isArray(parsed.form.turbineModels)
          ? parsed.form.turbineModels.map(createTurbineModelRow)
          : normalizeTurbineModelRows(parsed.form),
      },
      materialProjectMode: parsed.materialProjectMode === 'library' ? 'library' : 'ordinary',
      selectedMaterialProjectId: String(parsed.selectedMaterialProjectId || ''),
    }
  } catch {
    return null
  }
}

const writeDraft = (key, data) => {
  if (typeof window === 'undefined' || !key) return
  window.localStorage.setItem(key, JSON.stringify({
    version: TECHNICAL_PROJECT_WIZARD_DRAFT_VERSION,
    ...data,
    updatedAt: new Date().toISOString(),
  }))
}

const clearDraft = (key) => {
  if (typeof window === 'undefined' || !key) return
  window.localStorage.removeItem(key)
}

const materialProjectLabel = (item) => {
  const parts = [
    item.projectId,
    item.projectCode && item.projectCode !== item.projectId ? item.projectCode : '',
    item.customerName,
  ].filter(Boolean)
  return `${item.name}${parts.length ? `（${parts.join(' / ')}）` : ''}`
}

export default function TechnicalProjectWizardModal({
  onClose,
  onCreated,
  mode = 'create',
  project = null,
  prefill = null,
  allowParsePrefill = false,
  forceReviewDecision = '',
}) {
  const defaultBidType = TECHNICAL_BID_TYPE
  const requiresTurbineModel = true
  const projectsApi = technicalProjectsAPI
  const materialsApi = technicalMaterialsAPI
  const isUpdateMode = mode === 'update' && Boolean(project?.id)
  const draftKey = useMemo(() => buildDraftKey({ mode, project, defaultBidType }), [defaultBidType, mode, project])
  const draft = useMemo(() => readDraft(draftKey), [draftKey])
  const hasDraft = Boolean(draft)
  const [form, setForm] = useState(() => draft?.form || buildTechnicalProjectInitialForm({
    project,
    prefill,
    allowPrefill: allowParsePrefill || Boolean(project?.isParseDraft),
  }))
  const [materialProjectMode, setMaterialProjectMode] = useState(
    draft?.materialProjectMode || project?.materialProjectMode || (project?.materialProjectId ? 'library' : 'ordinary'),
  )
  const [materialProjects, setMaterialProjects] = useState([])
  const [selectedMaterialProjectId, setSelectedMaterialProjectId] = useState(
    draft?.selectedMaterialProjectId || String(project?.materialProjectId || ''),
  )
  const [projectInfoOptions, setProjectInfoOptions] = useState(STATIC_PROJECT_INFO_OPTIONS)
  // 客户 / 风机机型候选改为从技术标三级目录 JSON 索引派生（客户定制 / 标准文件），
  // 末尾固定带「其他」。见 doc/anbc_doc/20260618-技术标三级目录JSON索引-下游使用Handoff.md
  const [indexCustomerOptions, setIndexCustomerOptions] = useState([])
  const [indexTurbineModelOptions, setIndexTurbineModelOptions] = useState([])
  // 处于「其他」手动输入态的字段：客户用布尔，机型按行 id 记录。
  const [customerIsOther, setCustomerIsOther] = useState(false)
  const [otherTurbineRowIds, setOtherTurbineRowIds] = useState(() => new Set())
  const [loadingIdentities, setLoadingIdentities] = useState(false)
  const [identityError, setIdentityError] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const updateForm = (key, val) => setForm((prev) => ({ ...prev, [key]: val }))
  const selectedMaterialProject = materialProjects.find((item) => item.id === selectedMaterialProjectId)
  // 「其他」恒为最后一项，合并 form 现值时要避免把它当成真实候选重复插入。
  const customerOptions = useMemo(() => {
    const base = indexCustomerOptions.length ? indexCustomerOptions : projectInfoOptions.customers
    const extra = customerIsOther ? [] : [form.customerName]
    const merged = mergeOptionValues(base.filter((item) => item !== OTHER_OPTION_LABEL), extra)
    return [...merged, OTHER_OPTION_LABEL]
  }, [indexCustomerOptions, projectInfoOptions.customers, customerIsOther, form.customerName])
  const turbineModelOptions = useMemo(() => {
    const base = indexTurbineModelOptions.length ? indexTurbineModelOptions : projectInfoOptions.turbineModels
    const formModels = form.turbineModels
      .filter((row) => !otherTurbineRowIds.has(row.id))
      .map((row) => row.model)
    const merged = mergeOptionValues(base.filter((item) => item !== OTHER_OPTION_LABEL), formModels)
    return [...merged, OTHER_OPTION_LABEL]
  }, [indexTurbineModelOptions, projectInfoOptions.turbineModels, form.turbineModels, otherTurbineRowIds])

  const updateTurbineRow = (rowId, key, value) => {
    setForm((prev) => ({
      ...prev,
      turbineModels: prev.turbineModels.map((row) => (
        row.id === rowId ? { ...row, [key]: value } : row
      )),
    }))
  }

  const addTurbineRow = () => {
    setForm((prev) => ({
      ...prev,
      turbineModels: [...prev.turbineModels, createTurbineModelRow()],
    }))
  }

  const removeTurbineRow = (rowId) => {
    setOtherTurbineRowIds((prev) => {
      if (!prev.has(rowId)) return prev
      const next = new Set(prev)
      next.delete(rowId)
      return next
    })
    setForm((prev) => {
      const nextRows = prev.turbineModels.filter((row) => row.id !== rowId)
      return {
        ...prev,
        turbineModels: nextRows.length ? nextRows : [createTurbineModelRow()],
      }
    })
  }

  useEffect(() => {
    if (hasDraft || isUpdateMode || !defaultBidType) return
    const timer = setTimeout(() => {
      setForm((prev) => ({ ...prev, bidType: defaultBidType }))
    }, 0)
    return () => clearTimeout(timer)
  }, [defaultBidType, hasDraft, isUpdateMode])

  useEffect(() => {
    if (creating) return undefined
    const timer = setTimeout(() => {
      writeDraft(draftKey, {
        step: FORM_REQUIRED_STEP,
        form,
        materialProjectMode,
        selectedMaterialProjectId,
      })
    }, 250)
    return () => clearTimeout(timer)
  }, [
    creating,
    draftKey,
    form,
    materialProjectMode,
    selectedMaterialProjectId,
  ])

  useEffect(() => {
    let mounted = true
    const loadOptions = async () => {
      const options = await loadProjectInfoOptions(technicalProjectInfoOptionsAPI)
      if (!mounted) return
      // 仅作静态兜底；客户/机型默认值不再自动注入，候选以 JSON 索引派生为准，留空待用户选。
      setProjectInfoOptions(options)
    }
    loadOptions()
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    let mounted = true
    const loadIndexOptions = async () => {
      if (!materialsApi?.index) return
      try {
        const payload = await materialsApi.index()
        if (!mounted) return
        const customers = deriveCustomerOptionsFromIndex(payload)
        const turbines = deriveTurbineModelOptionsFromIndex(payload)
        setIndexCustomerOptions(customers)
        setIndexTurbineModelOptions(turbines)
        // 依据派生候选初始化「其他」手动态：现值非空且不在候选内 → 视为手动输入。
        const customerSet = new Set(customers.filter((item) => item !== OTHER_OPTION_LABEL))
        setCustomerIsOther((prev) => {
          const name = form.customerName.trim()
          return prev || Boolean(name && !customerSet.has(name))
        })
        const turbineSet = new Set(turbines.filter((item) => item !== OTHER_OPTION_LABEL))
        setOtherTurbineRowIds((prev) => {
          const next = new Set(prev)
          form.turbineModels.forEach((row) => {
            const model = String(row.model || '').trim()
            if (model && !turbineSet.has(model)) next.add(row.id)
          })
          return next
        })
      } catch {
        if (!mounted) return
        setIndexCustomerOptions([])
        setIndexTurbineModelOptions([])
      }
    }
    loadIndexOptions()
    return () => {
      mounted = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialsApi])

  useEffect(() => {
    let mounted = true
    const loadMaterialIdentities = async () => {
      setLoadingIdentities(true)
      setIdentityError('')
      try {
        if (!materialsApi?.identityOptions) {
          throw new Error('技术标素材身份接口未配置。')
        }
        const payload = await materialsApi.identityOptions({ bidType: form.bidType })
        if (!mounted) return
        const projects = normalizeMaterialProjects(payload?.projects || [])
        setMaterialProjects(projects)
        if (isUpdateMode) {
          if (hasDraft) return
          const selectedProject = projects.find((item) => item.id === String(project?.materialProjectId || ''))
          if (selectedProject) {
            setMaterialProjectMode(project?.materialProjectMode || 'library')
            setSelectedMaterialProjectId(selectedProject.id)
            setForm((prev) => ({
              ...prev,
              materialProjectName: selectedProject.name,
              projectCode: prev.projectCode || selectedProject.projectCode,
            }))
          }
          return
        }
        if (!hasDraft) {
          const defaultProject = projects[0]
          if (defaultProject) {
            setMaterialProjectMode('library')
            setSelectedMaterialProjectId(defaultProject.id)
            setForm((prev) => ({
              ...prev,
              materialProjectName: defaultProject.name,
              projectCode: prev.projectCode || defaultProject.projectCode,
            }))
          }
        }
      } catch (e) {
        if (!mounted) return
        setMaterialProjects([])
        setIdentityError(e?.message || '技术标项目候选加载失败，可选择普通项目。')
      } finally {
        if (mounted) setLoadingIdentities(false)
      }
    }
    loadMaterialIdentities()
    return () => {
      mounted = false
    }
  }, [form.bidType, hasDraft, isUpdateMode, materialsApi, project?.materialProjectId, project?.materialProjectMode])

  const missingRequiredItems = useMemo(() => {
    const items = []
    if (!form.name.trim()) items.push('项目名称')
    if (!form.customerName.trim()) items.push('客户')
    if (materialProjectMode === 'library' && !selectedMaterialProjectId) items.push('重点项目')
    const turbineRows = cleanTurbineModelRows(form.turbineModels)
    if (requiresTurbineModel && (!turbineRows.length || turbineRows.some((row) => !row.model))) items.push('风机机型')
    if (requiresTurbineModel && turbineRows.some((row) => !isPositiveIntegerText(row.turbineCount))) items.push('风机台数')
    if (requiresTurbineModel && turbineRows.some((row) => !row.foundationType.trim())) items.push('基础形式')
    if (!form.manager.trim()) items.push('负责人')
    if (!form.startDate) items.push('起始日期')
    if (!form.endDate) items.push('截止日期')
    return items
  }, [form, materialProjectMode, requiresTurbineModel, selectedMaterialProjectId])
  const canSubmit = missingRequiredItems.length === 0
  const nextDisabledReason = missingRequiredItems.length ? `请先补全：${missingRequiredItems.join('、')}` : ''

  const archivePathPreview = useMemo(() => {
    const bidType = form.bidType || '标书类型'
    const customer = form.customerName.trim() || '客户名'
    const projectIdentity = materialProjectMode === 'library'
      ? selectedMaterialProject?.projectId || selectedMaterialProjectId || '项目ID'
      : project?.materialProjectId || '系统生成项目ID'
    return `${bidType}/客户素材/${customer}；${bidType}/项目素材/${projectIdentity}`
  }, [form.bidType, form.customerName, materialProjectMode, project?.materialProjectId, selectedMaterialProject?.projectId, selectedMaterialProjectId])

  const handleCreate = async () => {
    setCreating(true)
    setCreateError('')
    try {
      const turbineModels = cleanTurbineModelRows(form.turbineModels)
      const primaryTurbineModel = buildPrimaryTurbineModel(turbineModels)
      const payload = {
        ...form,
        bidType: TECHNICAL_BID_TYPE,
        isParseDraft: false,
        turbineModels,
        deadline: form.endDate,
        owner: form.customerName,
        isKeyAccount: false,
        keyAccountId: '',
        customerId: '',
        customerCanonicalName: form.customerName,
        materialCustomerId: '',
        materialCustomerName: form.customerName,
        materialProjectMode,
        materialProjectId: materialProjectMode === 'library' ? selectedMaterialProject?.projectId || selectedMaterialProjectId : '',
        materialProjectCode: materialProjectMode === 'library' ? selectedMaterialProject?.projectCode || selectedMaterialProjectId : form.projectCode,
        materialProjectName: materialProjectMode === 'library' ? selectedMaterialProject?.name || selectedMaterialProjectId : (form.materialProjectName || form.name),
        turbineModel: requiresTurbineModel ? primaryTurbineModel : {},
      }
      if (forceReviewDecision) payload.reviewDecision = forceReviewDecision

      if (!projectsApi) throw new Error('技术标项目接口未配置。')
      if (isUpdateMode) {
        const updatedProject = await projectsApi.update(project.id, payload)
        clearDraft(draftKey)
        onCreated(updatedProject)
      } else {
        const createdProject = await projectsApi.create(payload)
        clearDraft(draftKey)
        onCreated(createdProject)
      }
    } catch (e) {
      console.error(e)
      setCreateError(e?.message || `${isUpdateMode ? '保存' : '创建'}失败，请稍后重试。`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="dialog-overlay bg-[rgba(23,33,43,0.28)] backdrop-blur-0" onClick={onClose}>
      <div
        className="dialog-content wizard-modal-surface w-full max-w-[760px] animate-fade-in border border-[#d1d9e4]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d8e0ea] bg-white">
          <div className="flex items-center gap-3">
            <h2 className="text-[18px] font-headline font-semibold text-on-surface">
              {isUpdateMode ? '完善项目信息' : '新建技术标项目'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="close-plain text-on-surface-variant hover:text-primary transition-colors"
            aria-label="关闭"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Step Content */}
        <div className="px-5 py-5 min-h-[410px] bg-white">
            <div className="flex flex-col gap-4 animate-fade-in">
              <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">项目名称 *</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="输入项目名称，例如：甘肃华能100MW风电项目"
                    value={form.name}
                    onChange={(e) => updateForm('name', e.target.value)}
                  />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">业务项目编号</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="例如：招标编号、项目编号"
                    value={form.projectCode}
                    onChange={(e) => updateForm('projectCode', e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">负责人 *</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="张建国"
                    value={form.manager}
                    onChange={(e) => updateForm('manager', e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-on-surface mb-2">客户 *</label>
                {customerIsOther ? (
                  <div className="flex items-center gap-2">
                    <input
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                      placeholder="输入客户名称"
                      autoFocus
                      value={form.customerName}
                      onChange={(e) => {
                        const customerName = e.target.value
                        setForm((prev) => ({
                          ...prev,
                          customerName,
                          customerId: '',
                          customerCanonicalName: customerName,
                        }))
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        setCustomerIsOther(false)
                        setForm((prev) => ({ ...prev, customerName: '', customerId: '', customerCanonicalName: '' }))
                      }}
                      className="h-9 px-3 shrink-0 border border-[#b8c7d8] bg-white text-xs font-semibold text-primary hover:bg-[#eef5fb] transition-colors"
                    >
                      选候选
                    </button>
                  </div>
                ) : (
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={form.customerName}
                    onChange={(e) => {
                      const value = e.target.value
                      if (value === OTHER_OPTION_LABEL) {
                        setCustomerIsOther(true)
                        setForm((prev) => ({ ...prev, customerName: '', customerId: '', customerCanonicalName: '' }))
                        return
                      }
                      setForm((prev) => ({
                        ...prev,
                        customerName: value,
                        customerId: '',
                        customerCanonicalName: value,
                      }))
                    }}
                  >
                    <option value="">选择客户</option>
                    {customerOptions.map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                )}
                {(identityError || loadingIdentities) && (
                  <p className={`text-xs mt-2 ${identityError ? 'text-error' : 'text-outline'}`}>
                    {identityError || '正在加载技术标项目...'}
                  </p>
                )}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">项目来源</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={materialProjectMode}
                    onChange={(e) => {
                      const nextMode = e.target.value
                      setMaterialProjectMode(nextMode)
                      if (nextMode === 'library') {
                        const selected = materialProjects.find((item) => item.id === selectedMaterialProjectId) || materialProjects[0]
                        if (selected) {
                          setSelectedMaterialProjectId(selected.id)
                          setForm((prev) => ({
                            ...prev,
                            materialProjectName: selected.name,
                            projectCode: prev.projectCode || selected.projectCode,
                          }))
                        }
                      }
                    }}
                    disabled={loadingIdentities}
                  >
                    <option value="library" disabled={!materialProjects.length}>重点项目</option>
                    <option value="ordinary">普通项目</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">
                    {materialProjectMode === 'library' ? '重点项目 *' : '普通项目'}
                  </label>
                  {materialProjectMode === 'library' && materialProjects.length > 0 ? (
                    <select
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                      value={selectedMaterialProjectId}
                      onChange={(e) => {
                        const nextId = e.target.value
                        setSelectedMaterialProjectId(nextId)
                        const selected = materialProjects.find((item) => item.id === nextId)
                        if (selected) {
                          setForm((prev) => ({
                            ...prev,
                            materialProjectName: selected.name,
                            projectCode: prev.projectCode || selected.projectCode,
                          }))
                        }
                      }}
                    >
                      <option value="">选择项目</option>
                      {materialProjects.map((item) => (
                        <option key={item.id} value={item.id}>{materialProjectLabel(item)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                      placeholder="项目名称，不填则使用投标项目名称"
                      value={form.materialProjectName}
                      onChange={(e) => updateForm('materialProjectName', e.target.value)}
                    />
                  )}
                </div>
              </div>
              {requiresTurbineModel && (
                <div className="border border-[#d2dce8] bg-[#f8fbfd] p-3">
                  <div className="flex items-center justify-between mb-3">
                    <label className="block text-sm font-semibold text-on-surface">风机机型明细 *</label>
                    <button
                      type="button"
                      onClick={addTurbineRow}
                      className="h-8 px-3 border border-[#b8c7d8] bg-white text-xs font-semibold text-primary hover:bg-[#eef5fb] transition-colors"
                    >
                      添加机型
                    </button>
                  </div>
                  <div className="flex flex-col gap-3">
                    {form.turbineModels.map((row, index) => (
                      <div key={row.id} className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_110px_minmax(0,1fr)_40px] gap-3 items-end">
                        <div>
                          <label className="block text-xs font-semibold text-outline mb-1">风机机型</label>
                          {otherTurbineRowIds.has(row.id) ? (
                            <div className="flex items-center gap-2">
                              <input
                                className="w-full min-h-0 h-9 px-3 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                                placeholder="输入风机机型"
                                autoFocus
                                value={row.model}
                                onChange={(e) => updateTurbineRow(row.id, 'model', e.target.value)}
                              />
                              <button
                                type="button"
                                onClick={() => {
                                  setOtherTurbineRowIds((prev) => {
                                    const next = new Set(prev)
                                    next.delete(row.id)
                                    return next
                                  })
                                  updateTurbineRow(row.id, 'model', '')
                                }}
                                className="h-9 px-2 shrink-0 border border-[#b8c7d8] bg-white text-xs font-semibold text-primary hover:bg-[#eef5fb] transition-colors"
                                title="返回候选选择"
                              >
                                候选
                              </button>
                            </div>
                          ) : (
                            <select
                              className="w-full min-h-0 h-9 px-3 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                              value={row.model}
                              onChange={(e) => {
                                const value = e.target.value
                                if (value === OTHER_OPTION_LABEL) {
                                  setOtherTurbineRowIds((prev) => new Set(prev).add(row.id))
                                  updateTurbineRow(row.id, 'model', '')
                                  return
                                }
                                updateTurbineRow(row.id, 'model', value)
                              }}
                            >
                              <option value="">选择风机机型</option>
                              {turbineModelOptions.map((item) => (
                                <option key={item} value={item}>{item}</option>
                              ))}
                            </select>
                          )}
                        </div>
                        <div>
                          <label className="block text-xs font-semibold text-outline mb-1">风机台数</label>
                          <input
                            inputMode="numeric"
                            pattern="[1-9][0-9]*"
                            className="w-full min-h-0 h-9 px-3 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                            placeholder="正整数"
                            value={row.turbineCount}
                            onChange={(e) => {
                              const value = e.target.value.replace(/\D/g, '')
                              updateTurbineRow(row.id, 'turbineCount', value)
                            }}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-semibold text-outline mb-1">基础形式</label>
                          <select
                            className="w-full min-h-0 h-9 px-3 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                            value={row.foundationType}
                            onChange={(e) => updateTurbineRow(row.id, 'foundationType', e.target.value)}
                          >
                            <option value="">选择基础形式</option>
                            {STATIC_FOUNDATION_TYPE_OPTIONS.map((item) => (
                              <option key={item} value={item}>{item}</option>
                            ))}
                          </select>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeTurbineRow(row.id)}
                          className="h-9 border border-[#d6dee9] bg-white text-on-surface-variant hover:text-error hover:border-error/40 transition-colors"
                          aria-label={`删除第 ${index + 1} 个风机机型`}
                          title="删除"
                        >
                          <span className="material-symbols-outlined text-[18px]">delete</span>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">起始日期 *</label>
                  <input
                    type="date"
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    value={form.startDate}
                    onChange={(e) => updateForm('startDate', e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">截止日期 *</label>
                  <input
                    type="date"
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    value={form.endDate}
                    onChange={(e) => updateForm('endDate', e.target.value)}
                  />
                </div>
              </div>
              {missingRequiredItems.length > 0 && (
                <div
                id="technical-project-required-hint"
                  className="border border-[#f2c169] bg-[#fff8e6] px-3 py-2 text-xs text-[#7a4d00]"
                >
                  {nextDisabledReason}
                </div>
              )}
              <div className="rounded-md border border-[#d2dce8] bg-[#f8fbfd] px-3 py-2">
                <p className="text-xs text-outline">材料归档路径预览</p>
                <p className="mt-1 text-sm font-medium text-on-surface">{archivePathPreview}</p>
              </div>
              {createError && (
                <div className="bg-error-container/30 border border-error/30 rounded-[4px] p-3 text-sm text-error">
                  {createError}
                </div>
              )}
            </div>
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-5 py-4 border-t border-[#d7e0ea] bg-white">
          <Button
            onClick={onClose}
            size="sm"
            variant="quiet"
          >
            取消
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating || !canSubmit}
            title={!canSubmit ? nextDisabledReason : undefined}
            aria-describedby={!canSubmit ? 'technical-project-required-hint' : undefined}
            size="stage"
            variant="primary"
          >
            {creating ? (isUpdateMode ? '保存中...' : '创建中...') : '确认提交'}
          </Button>
        </div>
      </div>
    </div>
  )
}
