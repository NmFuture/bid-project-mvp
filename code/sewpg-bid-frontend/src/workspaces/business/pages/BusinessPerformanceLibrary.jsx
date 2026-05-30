import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { businessMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/BusinessMaterialsViewSwitch'
import { workspaceRoute } from '../../../utils/workspace'

const BUSINESS_WORKSPACE = 'business'
const CATEGORY_STATUS_OPTIONS = [
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
  { value: 'all', label: '全部' },
]
const CATEGORY_STATUS_LABELS = {
  enabled: '启用',
  disabled: '停用',
}
const SCOPE_LABELS = {
  standard: '通用',
  customer: '客户',
  project: '项目',
}
const ATTACHMENT_LABELS = {
  summary_table: '汇总表',
  contract_bundle: '合同附件',
  other: '其他附件',
}
const SORTABLE_COLUMNS = [
  { key: 'name', label: '业绩类别' },
  { key: 'powerRating', label: '功率/场景' },
  { key: 'itemCount', label: '明细' },
  { key: 'fieldCount', label: '字段' },
  { key: 'attachmentCount', label: '附件' },
  { key: 'status', label: '状态' },
]

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
const compactParts = (...parts) => parts.map((part) => String(part || '').trim()).filter(Boolean).join(' · ')

const sizeLabel = (bytes) => {
  const value = Number(bytes || 0)
  if (!value) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const formatDateTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

const previewRows = (rows = [], limit = 5) => rows.slice(0, limit)

function SortHeader({ columnKey, label, sortBy, sortOrder, onSort, align = 'left' }) {
  const active = sortBy === columnKey
  const icon = active ? (sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'unfold_more'
  return (
    <button
      type="button"
      onClick={() => onSort(columnKey)}
      className={`inline-flex w-full items-center gap-1 text-xs font-semibold hover:text-primary ${align === 'right' ? 'justify-end' : 'justify-start'} ${active ? 'text-primary' : ''}`}
      title={`${label}排序`}
    >
      <span>{label}</span>
      <span className="material-symbols-outlined text-sm leading-none">{icon}</span>
    </button>
  )
}

export default function BusinessPerformanceLibrary({ showToast = () => {} }) {
  const summaryInputRef = useRef(null)
  const attachmentInputRef = useRef(null)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [previewing, setPreviewing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [uploadingCategoryId, setUploadingCategoryId] = useState('')
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [previewFile, setPreviewFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [importForm, setImportForm] = useState({ categoryName: '', scene: '', powerRating: '', tags: '' })
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [filters, setFilters] = useState({ keyword: '', scene: '', powerRating: '', tag: '', status: 'enabled' })
  const [sort, setSort] = useState({ sortBy: 'updatedAt', sortOrder: 'desc' })
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteConfirmName, setDeleteConfirmName] = useState('')
  const [deleting, setDeleting] = useState(false)
  const pageSize = 20
  const materialsBasePath = workspaceRoute(BUSINESS_WORKSPACE, '/materials')
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const query = useMemo(() => ({ ...filters, ...sort, page, pageSize }), [filters, sort, page])

  const loadCategories = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await businessMaterialsAPI.performance.categories(query)
      setItems(payload?.items || [])
      setTotal(Number(payload?.total || 0))
    } catch (error) {
      showToast(error?.message || '业绩库加载失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [query, showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadCategories()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadCategories])

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  const updateSort = (key) => {
    setSort((prev) => ({
      sortBy: key,
      sortOrder: prev.sortBy === key && prev.sortOrder === 'asc' ? 'desc' : 'asc',
    }))
    setPage(1)
  }

  const openSummaryChooser = () => {
    if (!summaryInputRef.current) return
    summaryInputRef.current.value = ''
    summaryInputRef.current.click()
  }

  const previewSummary = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const data = new FormData()
    data.append('file', file, file.name)
    setPreviewing(true)
    try {
      const result = await businessMaterialsAPI.performance.previewCategory(data)
      const nextPreview = result?.preview || null
      setPreviewFile(file)
      setPreview(nextPreview)
      setImportForm({
        categoryName: nextPreview?.categoryName || file.name.replace(/\.docx?$/i, ''),
        scene: nextPreview?.scene || '',
        powerRating: nextPreview?.powerRating || '',
        tags: tagsText([nextPreview?.scene, nextPreview?.powerRating, '业绩'].filter(Boolean)),
      })
    } catch (error) {
      showToast(error?.message || '业绩汇总表解析失败', 'error')
    } finally {
      setPreviewing(false)
    }
  }

  const closePreview = () => {
    setPreviewFile(null)
    setPreview(null)
    setImportForm({ categoryName: '', scene: '', powerRating: '', tags: '' })
  }

  const updateImportForm = (key, value) => {
    setImportForm((prev) => ({ ...prev, [key]: value }))
  }

  const confirmImport = async () => {
    if (!previewFile) return
    if (!importForm.categoryName.trim()) {
      showToast('请填写业绩类别名称', 'error')
      return
    }
    const data = new FormData()
    data.append('file', previewFile, previewFile.name)
    data.append('categoryName', importForm.categoryName.trim())
    data.append('scene', importForm.scene.trim())
    data.append('powerRating', importForm.powerRating.trim())
    data.append('tags', importForm.tags)
    data.append('scope', 'standard')
    data.append('reviewStatus', 'draft')
    setImporting(true)
    try {
      const result = await businessMaterialsAPI.performance.importCategory(data)
      showToast(result?.message || '业绩包已导入')
      closePreview()
      await loadCategories()
    } catch (error) {
      showToast(error?.message || '业绩包导入失败', 'error')
    } finally {
      setImporting(false)
    }
  }

  const openDetail = async (item) => {
    setDetailLoading(true)
    try {
      const payload = await businessMaterialsAPI.performance.category(item.id)
      setDetail(payload || null)
    } catch (error) {
      showToast(error?.message || '业绩明细加载失败', 'error')
    } finally {
      setDetailLoading(false)
    }
  }

  const chooseAttachmentFile = (item) => {
    setUploadingCategoryId(item.id)
    if (!attachmentInputRef.current) return
    attachmentInputRef.current.value = ''
    attachmentInputRef.current.click()
  }

  const uploadAttachment = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !uploadingCategoryId) return
    const data = new FormData()
    data.append('file', file, file.name)
    data.append('attachmentType', 'contract_bundle')
    setUploadingAttachment(true)
    try {
      const result = await businessMaterialsAPI.performance.uploadCategoryAttachment(uploadingCategoryId, data)
      showToast(result?.message || '合同附件已上传')
      await loadCategories()
      if (detail?.item?.id === uploadingCategoryId) {
        const payload = await businessMaterialsAPI.performance.category(uploadingCategoryId)
        setDetail(payload || null)
      }
    } catch (error) {
      showToast(error?.message || '合同附件上传失败', 'error')
    } finally {
      setUploadingAttachment(false)
      setUploadingCategoryId('')
    }
  }

  const toggleCategoryStatus = async (item) => {
    const nextStatus = item.status === 'disabled' ? 'enabled' : 'disabled'
    const nextLabel = CATEGORY_STATUS_LABELS[nextStatus]
    if (!window.confirm(`确认${nextLabel}业绩类别：${item.name || item.id}？`)) return
    try {
      const result = await businessMaterialsAPI.performance.updateCategoryStatus(item.id, { status: nextStatus })
      showToast(result?.message || `业绩类别已${nextLabel}`)
      await loadCategories()
      if (detail?.item?.id === item.id) {
        const payload = await businessMaterialsAPI.performance.category(item.id)
        setDetail(payload || null)
      }
    } catch (error) {
      showToast(error?.message || `业绩类别${nextLabel}失败`, 'error')
    }
  }

  const openDeleteDialog = (item) => {
    setDeleteTarget(item)
    setDeleteConfirmName('')
  }

  const closeDeleteDialog = () => {
    if (deleting) return
    setDeleteTarget(null)
    setDeleteConfirmName('')
  }

  const deleteCategory = async () => {
    if (!deleteTarget) return
    const expectedName = deleteTarget.name || deleteTarget.id
    if (deleteConfirmName.trim() !== expectedName) {
      showToast('请输入完整业绩类别名称后再删除', 'error')
      return
    }
    setDeleting(true)
    try {
      const result = await businessMaterialsAPI.performance.deleteCategory(deleteTarget.id, { confirmName: deleteConfirmName.trim() })
      showToast(result?.message || '业绩类别已删除')
      await loadCategories()
      if (detail?.item?.id === deleteTarget.id) setDetail(null)
      closeDeleteDialog()
    } catch (error) {
      showToast(error?.message || '业绩类别删除失败', 'error')
    } finally {
      setDeleting(false)
    }
  }

  const currentDetailItem = detail?.item
  const currentFields = currentDetailItem?.fieldSchema || []
  const visibleFields = currentFields.length ? currentFields : (preview?.fieldSchema || [])

  return (
    <main className="h-full min-h-0 overflow-hidden bg-surface text-on-surface">
      <input ref={summaryInputRef} type="file" accept=".docx" onChange={previewSummary} className="hidden" />
      <input ref={attachmentInputRef} type="file" accept=".doc,.docx" onChange={uploadAttachment} className="hidden" />
      <div className="flex h-full min-h-0 flex-col gap-3 px-4 py-4 sm:px-5 lg:px-6">
        <MaterialsViewSwitch
          active="performance"
          title="商务标共用业绩库"
          subtitle="按功率维护业绩包，汇总表字段用于筛选和后续任务填写"
          basePath={materialsBasePath}
          actions={
            <button
              onClick={openSummaryChooser}
              disabled={previewing}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-base">upload_file</span>
              {previewing ? '解析中...' : '导入业绩包'}
            </button>
          }
        />

        <section className="rounded-lg border border-surface-container-high bg-surface-container-lowest p-3">
          <div className="grid gap-2 md:grid-cols-5">
            <input value={filters.keyword} onChange={(event) => updateFilter('keyword', event.target.value)} placeholder="搜索类别/项目/买方/机型" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.scene} onChange={(event) => updateFilter('scene', event.target.value)} placeholder="陆上/海上" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.powerRating} onChange={(event) => updateFilter('powerRating', event.target.value)} placeholder="功率，如 11MW" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.tag} onChange={(event) => updateFilter('tag', event.target.value)} placeholder="标签" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <select value={filters.status} onChange={(event) => updateFilter('status', event.target.value)} className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm">
              {CATEGORY_STATUS_OPTIONS.map((option) => (
                <option key={option.label} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        </section>

        <section className="min-h-0 flex-1 overflow-auto rounded-lg border border-surface-container-high bg-white">
          {loading ? (
            <div className="p-6 text-sm text-on-surface-variant">加载中...</div>
          ) : !items.length ? (
            <div className="p-6 text-sm text-on-surface-variant">暂无业绩类别</div>
          ) : (
            <table className="w-full min-w-[1220px] text-left text-[12px] leading-5">
              <thead className="sticky top-0 bg-surface-container-low text-xs text-on-surface-variant">
                <tr>
                  {SORTABLE_COLUMNS.map((column) => (
                    <th key={column.key} className="px-3 py-2">
                      <SortHeader columnKey={column.key} label={column.label} sortBy={sort.sortBy} sortOrder={sort.sortOrder} onSort={updateSort} />
                    </th>
                  ))}
                  <th className="w-[230px] px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const itemTags = normalizeTags(item.tags)
                  const fieldLabels = (item.fieldSchema || []).map((field) => field.label || field.sourceHeader || field.key).filter(Boolean)
                  return (
                    <tr key={item.id} className="border-t border-surface-container-high align-top">
                      <td className="px-3 py-2.5">
                        <button onClick={() => openDetail(item)} className="max-w-[18rem] text-left text-[12.5px] font-semibold leading-5 text-primary hover:underline">
                          {item.name || item.id}
                        </button>
                        <div className="mt-1.5 flex max-w-[220px] flex-wrap gap-1">
                          <span className="rounded-full bg-surface-container-high px-1.5 py-0.5 text-[11px] leading-4 text-on-surface-variant">{SCOPE_LABELS[item.scope] || '通用'}</span>
                          {itemTags.map((tag) => (
                            <span key={tag} className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] leading-4 text-primary">{tag}</span>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="font-medium">{compactParts(item.scene, item.powerRating) || '-'}</div>
                        <div className="mt-0.5 text-[11px] leading-4 text-outline">更新 {formatDateTime(item.updatedAt) || '-'}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="inline-flex rounded-full bg-secondary-container px-1.5 py-0.5 text-[11px] font-semibold leading-4 text-on-secondary-container">
                          {Number(item.itemCount || 0)} 条
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="max-w-[19rem] text-on-surface-variant">{fieldLabels.slice(0, 5).join('、') || '-'}</div>
                        {fieldLabels.length > 5 ? <div className="mt-0.5 text-[11px] leading-4 text-outline">另 {fieldLabels.length - 5} 个字段</div> : null}
                      </td>
                      <td className="px-3 py-2.5">
                        <div>{item.summaryFileName || '未保存汇总表'}</div>
                        <div className="mt-0.5 text-[11px] leading-4 text-outline">
                          {item.contractAttachmentCount ? `合同附件：${item.contractFileName || `${item.contractAttachmentCount} 个`}` : '未上传合同附件'}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <div>
                          <span className={`rounded-full px-1.5 py-0.5 text-[11px] leading-4 ${item.status === 'disabled' ? 'bg-error-container/40 text-error' : 'bg-secondary-container text-on-secondary-container'}`}>
                            {CATEGORY_STATUS_LABELS[item.status] || '启用'}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex justify-end gap-1.5 whitespace-nowrap">
                          <button onClick={() => openDetail(item)} className="rounded-md bg-surface-container-high px-2 py-1 text-[11px] leading-4 hover:bg-surface-dim">明细</button>
                          <button disabled={uploadingAttachment && uploadingCategoryId === item.id} onClick={() => chooseAttachmentFile(item)} className="rounded-md bg-primary/10 px-2 py-1 text-[11px] leading-4 text-primary hover:bg-primary/15 disabled:opacity-50">
                            {uploadingAttachment && uploadingCategoryId === item.id ? '上传中...' : '上传合同'}
                          </button>
                          <button onClick={() => toggleCategoryStatus(item)} className={`rounded-md px-2 py-1 text-[11px] leading-4 ${item.status === 'disabled' ? 'bg-secondary-container text-on-secondary-container hover:bg-secondary-container/80' : 'bg-error-container/40 text-error hover:bg-error-container'}`}>
                            {item.status === 'disabled' ? '启用' : '停用'}
                          </button>
                          <button onClick={() => openDeleteDialog(item)} className="rounded-md bg-error-container/40 px-2 py-1 text-[11px] leading-4 text-error hover:bg-error-container">删除</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </section>

        <div className="flex items-center justify-between text-sm text-on-surface-variant">
          <span>共 {total} 个业绩类别</span>
          <div className="flex items-center gap-2">
            <button disabled={page <= 1} onClick={() => setPage((prev) => Math.max(1, prev - 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">上一页</button>
            <span>{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">下一页</button>
          </div>
        </div>
      </div>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-2xl">
            <div className="flex items-center justify-between border-b border-surface-container-high px-5 py-4">
              <div>
                <h2 className="text-base font-semibold">导入预览</h2>
                <p className="mt-1 text-xs text-on-surface-variant">{preview.sourceFileName} · {preview.rowCount} 条明细</p>
              </div>
              <button onClick={closePreview} className="close-plain text-on-surface-variant hover:text-primary" aria-label="关闭">x</button>
            </div>
            <div className="min-h-0 overflow-auto p-5">
              <div className="grid gap-3 md:grid-cols-4">
                <label className="text-sm text-on-surface-variant md:col-span-2">类别名称<input value={importForm.categoryName} onChange={(event) => updateImportForm('categoryName', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant">场景<input value={importForm.scene} onChange={(event) => updateImportForm('scene', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant">功率<input value={importForm.powerRating} onChange={(event) => updateImportForm('powerRating', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant md:col-span-4">标签<input value={importForm.tags} onChange={(event) => updateImportForm('tags', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
              </div>

              {preview.summary ? (
                <div className="mt-4 rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">{preview.summary}</div>
              ) : null}

              <div className="mt-4 overflow-auto rounded-lg border border-surface-container-high bg-white">
                <table className="w-full min-w-[980px] text-left text-xs">
                  <thead className="bg-surface-container-low text-on-surface-variant">
                    <tr>
                      {(preview.fieldSchema || []).map((field) => (
                        <th key={field.key || field.label} className="px-3 py-2">{field.label || field.sourceHeader || field.key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows(preview.rows).map((row) => (
                      <tr key={row.rowIndex} className="border-t border-surface-container-high">
                        {(preview.fieldSchema || []).map((field) => (
                          <td key={field.key || field.label} className="max-w-[16rem] truncate px-3 py-2">{row.values?.[field.sourceHeader || field.label] || '-'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
              <button onClick={closePreview} className="rounded-lg px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high">取消</button>
              <button onClick={confirmImport} disabled={importing} className="rounded-lg bg-primary px-4 py-2 text-sm text-on-primary disabled:opacity-50">{importing ? '导入中...' : '确认导入'}</button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg overflow-hidden rounded-xl border border-error/30 bg-surface-container-lowest shadow-2xl">
            <div className="border-b border-surface-container-high px-5 py-4">
              <h2 className="text-base font-semibold text-error">删除业绩类别</h2>
              <p className="mt-1 text-sm text-on-surface-variant">{deleteTarget.name || deleteTarget.id}</p>
            </div>
            <div className="p-5">
              <div className="rounded-lg bg-error-container/30 px-3 py-2 text-sm text-error">
                删除后会移除该类别、明细和已绑定附件，不能从停用列表恢复。
              </div>
              <label className="mt-4 block text-sm text-on-surface-variant">
                输入类别名称确认
                <input
                  value={deleteConfirmName}
                  onChange={(event) => setDeleteConfirmName(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-surface-container-high bg-surface-container-lowest px-3 text-sm text-on-surface"
                  autoFocus
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
              <button onClick={closeDeleteDialog} disabled={deleting} className="rounded-lg px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high disabled:opacity-50">取消</button>
              <button
                onClick={deleteCategory}
                disabled={deleting || deleteConfirmName.trim() !== (deleteTarget.name || deleteTarget.id)}
                className="rounded-lg bg-error px-4 py-2 text-sm text-on-error disabled:opacity-50"
              >
                {deleting ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-2xl">
            <div className="flex items-center justify-between border-b border-surface-container-high px-5 py-4">
              <div>
                <h2 className="text-base font-semibold">{currentDetailItem?.name || '业绩明细'}</h2>
                <p className="mt-1 text-xs text-on-surface-variant">{compactParts(currentDetailItem?.scene, currentDetailItem?.powerRating, `${currentDetailItem?.itemCount || 0} 条明细`)}</p>
              </div>
              <button onClick={() => setDetail(null)} className="close-plain text-on-surface-variant hover:text-primary" aria-label="关闭">x</button>
            </div>
            {detailLoading ? (
              <div className="p-6 text-sm text-on-surface-variant">加载中...</div>
            ) : (
              <div className="min-h-0 overflow-auto p-5">
                {currentDetailItem?.summary ? (
                  <div className="rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">{currentDetailItem.summary}</div>
                ) : null}

                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">附件</h3>
                    <button onClick={() => chooseAttachmentFile(currentDetailItem)} className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs text-primary hover:bg-primary/15">上传合同</button>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    {(detail.attachments || []).length ? detail.attachments.map((attachment) => (
                      <a
                        key={attachment.id}
                        href={businessMaterialsAPI.performance.categoryAttachmentUrl(attachment.categoryId, attachment.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-lg border border-surface-container-high bg-white px-3 py-2 text-sm hover:border-primary"
                      >
                        <span className="block font-medium text-primary">{attachment.fileName}</span>
                        <span className="mt-1 block text-xs text-outline">{ATTACHMENT_LABELS[attachment.attachmentType] || attachment.attachmentType} · {sizeLabel(attachment.sizeBytes) || '-'}</span>
                      </a>
                    )) : <div className="text-sm text-on-surface-variant">暂无附件</div>}
                  </div>
                </div>

                <div className="mt-4 overflow-auto rounded-lg border border-surface-container-high bg-white">
                  <table className="w-full min-w-[1080px] text-left text-xs">
                    <thead className="sticky top-0 bg-surface-container-low text-on-surface-variant">
                      <tr>
                        {visibleFields.map((field) => (
                          <th key={field.key || field.label} className="px-3 py-2">{field.label || field.sourceHeader || field.key}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.rows || []).map((row) => (
                        <tr key={row.id} className="border-t border-surface-container-high">
                          {visibleFields.map((field) => {
                            const label = field.sourceHeader || field.label
                            return <td key={field.key || field.label} className="max-w-[18rem] px-3 py-2 align-top">{row.values?.[label] || '-'}</td>
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  )
}
