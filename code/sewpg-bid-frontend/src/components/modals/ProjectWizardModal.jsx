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

export default function ProjectWizardModal({ onClose, onCreated }) {
  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    name: '',
    customerName: '',
    manager: '',
    bidType: '技术标',
    deadline: '',
  })
  const [customerMode, setCustomerMode] = useState('manual')
  const [keyAccounts, setKeyAccounts] = useState([])
  const [selectedKeyAccountId, setSelectedKeyAccountId] = useState('')
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
        if (list.length > 0) {
          setCustomerMode('keyAccount')
          setSelectedKeyAccountId(list[0].id)
          setForm((prev) => ({ ...prev, customerName: list[0].name }))
        }
      } catch (e) {
        if (!mounted) return
        setKeyAccounts([])
        setCustomerMode('manual')
        setAccountError(e?.message || '重点客户字典加载失败，可手动输入客户名称。')
      } finally {
        if (mounted) setLoadingAccounts(false)
      }
    }
    loadAccounts()
    return () => {
      mounted = false
    }
  }, [])

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
      const project = await projectsAPI.create(payload)
      onCreated(project)
    } catch (e) {
      console.error(e)
      setCreateError(e?.message || '创建失败，请稍后重试。')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content w-full max-w-2xl animate-fade-in" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-8 py-6 border-b border-surface-container-high">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-2xl">add_circle</span>
            <h2 className="text-xl font-headline font-bold text-on-surface">新建投标项目</h2>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full hover:bg-surface-container-high transition-colors flex items-center justify-center">
            <span className="material-symbols-outlined text-on-surface-variant">close</span>
          </button>
        </div>

        {/* Step Indicator */}
        <div className="flex items-center gap-4 px-8 py-4 bg-surface-container-low">
          {STEPS.map((label, i) => (
            <div key={i} className="flex items-center gap-2 flex-1">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${
                i < step ? 'bg-secondary text-on-secondary' : i === step ? 'bg-primary text-on-primary' : 'bg-surface-container-high text-outline'
              }`}>
                {i < step ? <span className="material-symbols-outlined text-sm">check</span> : i + 1}
              </div>
              <span className={`text-sm font-medium ${i === step ? 'text-primary' : 'text-outline'}`}>{label}</span>
              {i < STEPS.length - 1 && <div className={`flex-1 h-0.5 ${i < step ? 'bg-secondary' : 'bg-surface-container-high'}`}></div>}
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="px-8 py-6 min-h-[320px]">
          {step === 0 && (
            <div className="flex flex-col gap-5 animate-fade-in">
              <div>
                <label className="block text-sm font-medium text-on-surface mb-2">项目名称 *</label>
                <input
                  className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-2 focus:ring-primary/30 transition-all"
                  placeholder="输入项目名称，例如：甘肃华能100MW风电项目"
                  value={form.name}
                  onChange={(e) => updateForm('name', e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-on-surface mb-2">客户类型</label>
                  <select
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 transition-all cursor-pointer"
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
                  <label className="block text-sm font-medium text-on-surface mb-2">负责人 *</label>
                  <input
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-2 focus:ring-primary/30 transition-all"
                    placeholder="张建国"
                    value={form.manager}
                    onChange={(e) => updateForm('manager', e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-on-surface mb-2">业主单位（客户） *</label>
                {customerMode === 'keyAccount' && keyAccounts.length > 0 ? (
                  <select
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 transition-all cursor-pointer"
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
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-2 focus:ring-primary/30 transition-all"
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
                  <label className="block text-sm font-medium text-on-surface mb-2">截止日期 *</label>
                  <input
                    type="date"
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-2 focus:ring-primary/30 transition-all"
                    value={form.deadline}
                    onChange={(e) => updateForm('deadline', e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-on-surface mb-2">标书类型</label>
                  <select
                    className="w-full h-11 px-4 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 transition-all cursor-pointer"
                    value={form.bidType}
                    onChange={(e) => updateForm('bidType', e.target.value)}
                  >
                    <option>技术标</option>
                    <option>商务标</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-5 animate-fade-in">
              <div className="bg-surface-container-low rounded-xl p-6">
                <h3 className="text-sm font-semibold text-on-surface-variant mb-4 uppercase tracking-wider">项目概览</h3>
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
                <div className="mt-4 pt-4 border-t border-surface-container-high">
                  <p className="text-xs text-outline">材料归档路径预览</p>
                  <p className="text-sm font-medium text-on-surface mt-1">{archivePathPreview}</p>
                </div>
              </div>
              <div className="bg-secondary-container/20 border border-secondary/20 rounded-lg p-4 flex items-start gap-3">
                <span className="material-symbols-outlined text-secondary mt-0.5">info</span>
                <p className="text-sm text-on-surface-variant">创建后进入 S1 阶段上传招标文件（必选）与模板文件（可选），上传成功后将自动触发解析。</p>
              </div>
              {createError && (
                <div className="bg-error-container/30 border border-error/30 rounded-lg p-3 text-sm text-error">
                  {createError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-8 py-4 border-t border-surface-container-high bg-surface-container-low rounded-b-xl">
          <button
            onClick={() => (step === 0 ? onClose() : setStep(step - 1))}
            className="px-5 py-2.5 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors"
          >
            {step === 0 ? '取消' : '上一步'}
          </button>
          {step < 1 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canNextStep}
              className="px-5 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
            >
              下一步
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-6 py-2.5 bg-gradient-to-r from-primary to-primary-container text-on-primary text-sm font-semibold rounded-lg hover:shadow-lg shadow-primary/20 transition-all active:scale-95 disabled:opacity-50 flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">rocket_launch</span>
              {creating ? '创建中...' : '确认创建'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
