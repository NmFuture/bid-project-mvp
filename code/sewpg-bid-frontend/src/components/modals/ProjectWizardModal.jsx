import { useEffect, useMemo, useState } from 'react'
import { customersAPI, projectsAPI } from '../../api'

const STEPS = ['基本信息', '确认创建']

const normalizeKeyAccounts = (list = []) =>
  (Array.isArray(list) ? list : [])
    .map((item) => ({
      id: String(item?.id || item?.code || item?.name || '').trim(),
      name: String(item?.name || item?.label || item?.id || '').trim(),
    }))
    .filter((item) => item.id && item.name)

const buildInitialForm = (project = null) => ({
  name: String(project?.name || ''),
  customerName: String(project?.customerName || ''),
  manager: String(project?.manager || ''),
  bidType: String(project?.bidType || '技术标'),
  deadline: String(project?.deadline || ''),
})

export default function ProjectWizardModal({
  onClose,
  onCreated,
  mode = 'create',
  project = null,
  forceReviewDecision = '',
}) {
  const isUpdateMode = mode === 'update' && Boolean(project?.id)
  const [step, setStep] = useState(0)
  const [form, setForm] = useState(() => buildInitialForm(project))
  const [customerMode, setCustomerMode] = useState(
    project?.isKeyAccount ? 'keyAccount' : 'manual',
  )
  const [keyAccounts, setKeyAccounts] = useState([])
  const [selectedKeyAccountId, setSelectedKeyAccountId] = useState(
    String(project?.keyAccountId || ''),
  )
  const [loadingAccounts, setLoadingAccounts] = useState(false)
  const [accountError, setAccountError] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const updateForm = (key, val) => setForm((prev) => ({ ...prev, [key]: val }))

  useEffect(() => {
    let mounted = true
    const loadAccounts = async () => {
      setLoadingAccounts(true)
      setAccountError('')
      try {
        const payload = await customersAPI.keyAccounts()
        if (!mounted) return
        const list = normalizeKeyAccounts(payload?.items || payload)
        setKeyAccounts(list)
        if (isUpdateMode) {
          if (project?.isKeyAccount && list.length > 0) {
            const selected = list.find((item) => item.id === String(project?.keyAccountId || ''))
              || list.find((item) => item.name === String(project?.customerName || ''))
              || list[0]
            setCustomerMode('keyAccount')
            setSelectedKeyAccountId(selected.id)
            setForm((prev) => ({ ...prev, customerName: selected.name }))
          }
          return
        }
        if (list.length > 0) {
          setCustomerMode('keyAccount')
          setSelectedKeyAccountId(list[0].id)
          setForm((prev) => ({ ...prev, customerName: list[0].name }))
        }
      } catch (e) {
        if (!mounted) return
        setKeyAccounts([])
        if (!isUpdateMode) setCustomerMode('manual')
        setAccountError(e?.message || '重点客户字典加载失败，可手动输入客户名称。')
      } finally {
        if (mounted) setLoadingAccounts(false)
      }
    }
    loadAccounts()
    return () => {
      mounted = false
    }
  }, [isUpdateMode, project?.customerName, project?.isKeyAccount, project?.keyAccountId])

  const canNextStep = useMemo(() => {
    if (step !== 0) return true
    if (!form.name.trim()) return false
    if (!form.customerName.trim()) return false
    if (!form.manager.trim()) return false
    if (!form.deadline) return false
    return true
  }, [form, step])

  const archivePathPreview = useMemo(() => {
    const customer = form.customerName.trim() || '客户名'
    if (customerMode === 'keyAccount') {
      return `客户定制/${customer}/{项目ID}/${form.bidType}`
    }
    return `项目定制/{项目ID}/${form.bidType}`
  }, [customerMode, form.customerName, form.bidType])

  const handleCreate = async () => {
    setCreating(true)
    setCreateError('')
    try {
      const payload = {
        ...form,
        owner: form.customerName,
        isKeyAccount: customerMode === 'keyAccount' && Boolean(selectedKeyAccountId),
        keyAccountId: customerMode === 'keyAccount' ? selectedKeyAccountId : '',
      }
      if (forceReviewDecision) payload.reviewDecision = forceReviewDecision

      if (isUpdateMode) {
        const updatedProject = await projectsAPI.update(project.id, payload)
        onCreated(updatedProject)
      } else {
        const createdProject = await projectsAPI.create(payload)
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
              {isUpdateMode ? '完善项目信息' : '新建投标项目'}
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

        {/* Step Indicator */}
        <div className="flex items-center gap-3 px-5 py-3 bg-white border-b border-[#d7e0ea]">
          {STEPS.map((label, i) => (
            <div key={i} className="flex items-center gap-2 flex-1">
              <div
                className={`step-circle w-8 h-8 flex items-center justify-center text-sm font-semibold ${
                  i < step
                    ? 'bg-[#0068b7] text-white'
                    : i === step
                      ? 'bg-[#0068b7] text-white'
                      : 'bg-[#dbe4ee] text-[#8193a8]'
                }`}
              >
                {i < step ? <span className="material-symbols-outlined text-[16px]">check</span> : i + 1}
              </div>
              <span className={`text-sm font-medium ${i === step || i < step ? 'text-[#0068b7]' : 'text-[#8193a8]'}`}>{label}</span>
              {i < STEPS.length - 1 && (
                <div className={`flex-1 h-[1px] ${i < step ? 'bg-[#0068b7]' : 'bg-[#d0dbe7]'}`}></div>
              )}
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="px-5 py-5 min-h-[410px] bg-white">
          {step === 0 && (
            <div className="flex flex-col gap-4 animate-fade-in">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">标书类型</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={form.bidType}
                    onChange={(e) => updateForm('bidType', e.target.value)}
                  >
                    <option>技术标</option>
                    <option>商务标</option>
                  </select>
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm font-semibold text-on-surface mb-2">项目名称 *</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="输入项目名称，例如：甘肃华能100MW风电项目"
                    value={form.name}
                    onChange={(e) => updateForm('name', e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">客户类型</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={customerMode}
                    onChange={(e) => {
                      const nextMode = e.target.value
                      setCustomerMode(nextMode)
                      if (nextMode === 'keyAccount') {
                        const selected = keyAccounts.find((item) => item.id === selectedKeyAccountId) || keyAccounts[0]
                        if (selected) {
                          setSelectedKeyAccountId(selected.id)
                          setForm((prev) => ({ ...prev, customerName: selected.name }))
                        }
                      }
                    }}
                    disabled={loadingAccounts}
                  >
                    <option value="keyAccount" disabled={!keyAccounts.length}>重点客户</option>
                    <option value="manual">普通客户（手动输入）</option>
                  </select>
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
                <label className="block text-sm font-semibold text-on-surface mb-2">业主单位（客户） *</label>
                {customerMode === 'keyAccount' && keyAccounts.length > 0 ? (
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={selectedKeyAccountId}
                    onChange={(e) => {
                      const nextId = e.target.value
                      setSelectedKeyAccountId(nextId)
                      const selected = keyAccounts.find((item) => item.id === nextId)
                      if (selected) {
                        setForm((prev) => ({ ...prev, customerName: selected.name }))
                      }
                    }}
                  >
                    {keyAccounts.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="输入客户名称，例如：华能集团"
                    value={form.customerName}
                    onChange={(e) => updateForm('customerName', e.target.value)}
                  />
                )}
                {(accountError || loadingAccounts) && (
                  <p className={`text-xs mt-2 ${accountError ? 'text-error' : 'text-outline'}`}>
                    {accountError || '正在加载重点客户字典...'}
                  </p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">截止日期 *</label>
                  <input
                    type="date"
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    value={form.deadline}
                    onChange={(e) => updateForm('deadline', e.target.value)}
                  />
                </div>
                <div className="hidden md:block" />
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-4 animate-fade-in">
              <div className="bg-[#ffffff] border border-[#d2dce8] rounded-[4px] p-5">
                <h3 className="text-[16px] font-semibold text-on-surface mb-4">
                  {isUpdateMode ? '项目信息确认' : '项目概览'}
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {[
                    ['项目名称', form.name || '—'],
                    ['业主单位', form.customerName || '—'],
                    ['负责人', form.manager || '—'],
                    ['标书类型', form.bidType],
                    ['截止日期', form.deadline || '—'],
                  ].map(([label, value], i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <span className="text-xs text-outline">{label}</span>
                      <span className="text-sm font-medium text-on-surface">{value}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-[#cfdae7]">
                  <p className="text-xs text-outline">材料归档路径预览</p>
                  <p className="text-sm font-medium text-on-surface mt-1">{archivePathPreview}</p>
                </div>
              </div>
              {createError && (
                <div className="bg-error-container/30 border border-error/30 rounded-[4px] p-3 text-sm text-error">
                  {createError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-5 py-4 border-t border-[#d7e0ea] bg-white">
          <button
            onClick={() => (step === 0 ? onClose() : setStep(step - 1))}
            className="h-8 px-6 text-sm font-medium text-white border border-[#a8acaf] bg-[#b6babd] hover:bg-[#a9adb0] transition-colors"
          >
            {step === 0 ? '取消' : '上一步'}
          </button>
          {step < 1 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canNextStep}
              className="h-8 px-6 bg-[#0bafff] text-on-primary text-sm font-medium border border-[#0aa3ea] hover:bg-[#07a3ef] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              下一步
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={creating}
              className="h-8 px-7 bg-[#0bafff] text-on-primary text-sm font-semibold border border-[#0aa3ea] hover:bg-[#07a3ef] transition-colors disabled:opacity-50"
            >
              {creating ? (isUpdateMode ? '保存中...' : '创建中...') : (isUpdateMode ? '确认提交' : '确认创建')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
