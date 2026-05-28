import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { businessMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/BusinessMaterialsViewSwitch'
import { workspaceRoute } from '../../../utils/workspace'

const BUSINESS_WORKSPACE = 'business'
const BID_TYPE_OPTIONS = ['商务标', '技术标']
const SCOPE_OPTIONS = [
  { value: 'standard', label: '通用' },
  { value: 'customer', label: '客户' },
  { value: 'project', label: '项目' },
]
const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'reviewed', label: '已审核' },
  { value: 'disabled', label: '停用' },
]
const EMPTY_FORM = {
  name: '',
  customerName: '',
  projectType: '',
  scale: '',
  location: '',
  startedAt: '',
  completedAt: '',
  amount: '',
  turbineModel: '',
  tags: '',
  applicableBidTypes: ['商务标'],
  scope: 'standard',
  reviewStatus: 'draft',
}

const normalizeTags = (value) => {
  const source = Array.isArray(value) ? value : String(value || '').split(/[,，;；\n\r\t]+/)
  const seen = new Set()
  const tags = []
  source.forEach((item) => {
    const tag = String(item || '').replace(/\s+/g, ' ').trim().slice(0, 40)
    if (!tag) return
    const key = tag.toLocaleLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    tags.push(tag)
  })
  return tags.slice(0, 20)
}

const tagsText = (value) => normalizeTags(value).join('，')

const sizeLabel = (bytes) => {
  const value = Number(bytes || 0)
  if (!value) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

export default function BusinessPerformanceLibrary({ showToast = () => {} }) {
  const fileInputRef = useRef(null)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [uploadingId, setUploadingId] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingItem, setEditingItem] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [filters, setFilters] = useState({ keyword: '', customerName: '', bidType: '', tag: '' })
  const pageSize = 20
  const materialsBasePath = workspaceRoute(BUSINESS_WORKSPACE, '/materials')
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const query = useMemo(() => ({ ...filters, page, pageSize }), [filters, page])

  const loadRecords = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await businessMaterialsAPI.performance.list(query)
      setItems(payload?.items || [])
      setTotal(Number(payload?.total || 0))
    } catch (error) {
      showToast(error?.message || '业绩库加载失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [query, showToast])

  useEffect(() => {
    loadRecords()
  }, [loadRecords])

  const openCreate = () => {
    setEditingItem(null)
    setForm(EMPTY_FORM)
    setShowForm(true)
  }

  const openEdit = (item) => {
    setEditingItem(item)
    setShowForm(true)
    setForm({
      name: item.name || '',
      customerName: item.customerName || '',
      projectType: item.projectType || '',
      scale: item.scale || '',
      location: item.location || '',
      startedAt: item.startedAt || '',
      completedAt: item.completedAt || '',
      amount: item.amount || '',
      turbineModel: item.turbineModel || '',
      tags: tagsText(item.tags),
      applicableBidTypes: item.applicableBidTypes?.length ? item.applicableBidTypes : ['商务标'],
      scope: item.scope || 'standard',
      reviewStatus: item.reviewStatus || 'draft',
    })
  }

  const closeForm = () => {
    setShowForm(false)
    setEditingItem(null)
    setForm(EMPTY_FORM)
  }

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const toggleBidType = (bidType) => {
    setForm((prev) => {
      const current = new Set(prev.applicableBidTypes || [])
      if (current.has(bidType)) current.delete(bidType)
      else current.add(bidType)
      return { ...prev, applicableBidTypes: Array.from(current) }
    })
  }

  const saveRecord = async () => {
    if (!form.name.trim()) {
      showToast('请填写业绩名称', 'error')
      return
    }
    setSaving(true)
    const payload = {
      ...form,
      tags: normalizeTags(form.tags),
      applicableBidTypes: form.applicableBidTypes?.length ? form.applicableBidTypes : ['商务标'],
    }
    try {
      const result = editingItem?.id
        ? await businessMaterialsAPI.performance.update(editingItem.id, payload)
        : await businessMaterialsAPI.performance.create(payload)
      showToast(result?.message || '业绩记录已保存')
      closeForm()
      await loadRecords()
    } catch (error) {
      showToast(error?.message || '业绩记录保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const deleteRecord = async (item) => {
    if (!window.confirm(`确认删除业绩：${item.name || item.id}？`)) return
    try {
      const result = await businessMaterialsAPI.performance.delete(item.id)
      showToast(result?.message || '业绩记录已删除')
      await loadRecords()
    } catch (error) {
      showToast(error?.message || '业绩记录删除失败', 'error')
    }
  }

  const chooseWordFile = (item) => {
    setUploadingId(item.id)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
      fileInputRef.current.click()
    }
  }

  const uploadWord = async (event) => {
    const file = event.target.files?.[0]
    if (!file || !uploadingId) return
    const data = new FormData()
    data.append('file', file, file.name)
    try {
      const result = await businessMaterialsAPI.performance.uploadWord(uploadingId, data)
      showToast(result?.message || '业绩 Word 已上传')
      await loadRecords()
    } catch (error) {
      showToast(error?.message || '业绩 Word 上传失败', 'error')
    } finally {
      setUploadingId('')
      event.target.value = ''
    }
  }

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  return (
    <main className="h-full min-h-0 overflow-hidden bg-surface text-on-surface">
      <input ref={fileInputRef} type="file" accept=".doc,.docx" onChange={uploadWord} className="hidden" />
      <div className="flex h-full min-h-0 flex-col gap-3 px-4 py-4 sm:px-5 lg:px-6">
        <MaterialsViewSwitch
          active="performance"
          title="商务标共用业绩库"
          subtitle="沉淀可复用业绩字段和 Word 证明文件"
          basePath={materialsBasePath}
          actions={
            <button onClick={openCreate} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container">
              新增业绩
            </button>
          }
        />

        <section className="rounded-lg border border-surface-container-high bg-surface-container-lowest p-3">
          <div className="grid gap-2 md:grid-cols-4">
            <input value={filters.keyword} onChange={(e) => updateFilter('keyword', e.target.value)} placeholder="搜索业绩/客户/类型" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.customerName} onChange={(e) => updateFilter('customerName', e.target.value)} placeholder="客户名称" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.tag} onChange={(e) => updateFilter('tag', e.target.value)} placeholder="标签" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <select value={filters.bidType} onChange={(e) => updateFilter('bidType', e.target.value)} className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm">
              <option value="">全部标类</option>
              {BID_TYPE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
        </section>

        <section className="min-h-0 flex-1 overflow-auto rounded-lg border border-surface-container-high bg-white">
          {loading ? (
            <div className="p-6 text-sm text-on-surface-variant">加载中...</div>
          ) : !items.length ? (
            <div className="p-6 text-sm text-on-surface-variant">暂无业绩记录</div>
          ) : (
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="sticky top-0 bg-surface-container-low text-xs text-on-surface-variant">
                <tr>
                  <th className="px-3 py-2">业绩</th>
                  <th className="px-3 py-2">客户</th>
                  <th className="px-3 py-2">类型/金额</th>
                  <th className="px-3 py-2">标签</th>
                  <th className="px-3 py-2">适用标类</th>
                  <th className="px-3 py-2">Word</th>
                  <th className="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-t border-surface-container-high">
                    <td className="px-3 py-3">
                      <div className="font-semibold text-on-surface">{item.name || '-'}</div>
                      <div className="mt-1 text-xs text-outline">{item.location || '-'} · {item.startedAt || '-'} 至 {item.completedAt || '-'}</div>
                    </td>
                    <td className="px-3 py-3">{item.customerName || '-'}</td>
                    <td className="px-3 py-3">
                      <div>{item.projectType || '-'}</div>
                      <div className="mt-1 text-xs text-outline">{item.amount || item.scale || '-'}</div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex max-w-[220px] flex-wrap gap-1">
                        {normalizeTags(item.tags).map((tag) => (
                          <span key={tag} className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">{tag}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-3">{(item.applicableBidTypes || []).join('、') || '-'}</td>
                    <td className="px-3 py-3">
                      {item.wordObjectKey ? (
                        <a className="text-primary hover:underline" href={businessMaterialsAPI.performance.wordUrl(item.id)} target="_blank" rel="noreferrer">
                          {item.wordFileName || '下载 Word'} {sizeLabel(item.wordSizeBytes)}
                        </a>
                      ) : (
                        <span className="text-outline">未上传</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-2">
                        <button onClick={() => openEdit(item)} className="rounded-md bg-surface-container-high px-2.5 py-1.5 text-xs hover:bg-surface-dim">编辑</button>
                        <button onClick={() => chooseWordFile(item)} className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs text-primary hover:bg-primary/15">上传 Word</button>
                        <button onClick={() => deleteRecord(item)} className="rounded-md bg-error-container/40 px-2.5 py-1.5 text-xs text-error hover:bg-error-container">删除</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <div className="flex items-center justify-between text-sm text-on-surface-variant">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-2">
            <button disabled={page <= 1} onClick={() => setPage((prev) => Math.max(1, prev - 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">上一页</button>
            <span>{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">下一页</button>
          </div>
        </div>
      </div>

      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-2xl">
            <div className="flex items-center justify-between border-b border-surface-container-high px-5 py-4">
              <h2 className="text-base font-semibold">{editingItem?.id ? '编辑业绩' : '新增业绩'}</h2>
              <button onClick={closeForm} className="close-plain text-on-surface-variant hover:text-primary" aria-label="关闭">x</button>
            </div>
            <div className="grid gap-3 p-5 md:grid-cols-2">
              <label className="text-sm text-on-surface-variant md:col-span-2">业绩名称<input value={form.name} onChange={(e) => updateField('name', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">客户<input value={form.customerName} onChange={(e) => updateField('customerName', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">项目类型<input value={form.projectType} onChange={(e) => updateField('projectType', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">规模<input value={form.scale} onChange={(e) => updateField('scale', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">地点<input value={form.location} onChange={(e) => updateField('location', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">开始时间<input value={form.startedAt} onChange={(e) => updateField('startedAt', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">完成时间<input value={form.completedAt} onChange={(e) => updateField('completedAt', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">金额<input value={form.amount} onChange={(e) => updateField('amount', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">机型<input value={form.turbineModel} onChange={(e) => updateField('turbineModel', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant md:col-span-2">标签<input value={form.tags} onChange={(e) => updateField('tags', e.target.value)} placeholder="业绩，资格，评分响应" className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm" /></label>
              <label className="text-sm text-on-surface-variant">范围<select value={form.scope} onChange={(e) => updateField('scope', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm">{SCOPE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
              <label className="text-sm text-on-surface-variant">审核状态<select value={form.reviewStatus} onChange={(e) => updateField('reviewStatus', e.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm">{STATUS_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
              <div className="text-sm text-on-surface-variant md:col-span-2">
                <span className="block mb-2">适用标类</span>
                <div className="flex gap-3">
                  {BID_TYPE_OPTIONS.map((item) => (
                    <label key={item} className="inline-flex items-center gap-2">
                      <input type="checkbox" checked={form.applicableBidTypes.includes(item)} onChange={() => toggleBidType(item)} />
                      {item}
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
              <button onClick={closeForm} className="rounded-lg px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high">取消</button>
              <button onClick={saveRecord} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm text-on-primary disabled:opacity-50">{saving ? '保存中...' : '保存'}</button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
