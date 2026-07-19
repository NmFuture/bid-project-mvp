import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { performanceAPI } from '../../../api'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import MaterialsViewSwitch from '../components/SharedMaterialsViewSwitch'
import { availableWorkspacesFor, defaultWorkspaceFor } from '../../../utils/permissions'
import { workspaceRoute } from '../../../utils/workspace'

const WORKSPACE_STORAGE_KEY = 'sewpg.workspace'
const CATEGORY_STATUS_OPTIONS = [
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
  { value: 'all', label: '全部' },
]
const CATEGORY_STATUS_LABELS = {
  enabled: '启用',
  disabled: '停用',
}
const ATTACHMENT_LABELS = {
  summary_table: '汇总表',
  contract_bundle: '合同附件',
  other: '其他附件',
}
const SORTABLE_COLUMNS = [
  { key: 'projectName', label: '项目名称' },
  { key: 'customerName', label: '买方' },
  { key: 'turbineModel', label: '型号' },
  { key: 'contractYear', label: '合同年' },
  { key: 'deliveryYear', label: '交货/投运' },
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
const compactList = (value, limit = 4) => {
  const list = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : []
  if (!list.length) return '-'
  const visible = list.slice(0, limit).join('、')
  return list.length > limit ? `${visible} 等${list.length}项` : visible
}
const compactYears = (...groups) => {
  const values = []
  const seen = new Set()
  groups.flat().forEach((item) => {
    if (item === null || item === undefined || item === '') return
    const value = Number(item)
    if (!Number.isFinite(value) || seen.has(value)) return
    seen.add(value)
    values.push(value)
  })
  values.sort((a, b) => a - b)
  return values.length ? values.join('、') : '-'
}

const sizeLabel = (bytes) => {
  const value = Number(bytes || 0)
  if (!value) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const previewRows = (rows = [], limit = 5) => rows.slice(0, limit)

const sourceWorkspaceFor = (user) => {
  const allowed = availableWorkspacesFor(user)
  if (typeof window !== 'undefined') {
    const stored = window.sessionStorage.getItem(WORKSPACE_STORAGE_KEY)
    if (allowed.includes(stored)) return stored
  }
  return defaultWorkspaceFor(user) || 'business'
}

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

function AttachmentHoverActions({
  onPreview,
  downloadUrl,
  previewLabel = 'OnlyOffice 预览',
  downloadLabel = '下载原件',
}) {
  return (
    <span className="inline-flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
      <button
        type="button"
        title={previewLabel}
        aria-label={previewLabel}
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onPreview?.()
        }}
        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-white text-outline shadow-sm ring-1 ring-surface-container-high hover:bg-primary/10 hover:text-primary"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[16px]">visibility</span>
      </button>
      {downloadUrl ? (
        <a
          href={downloadUrl}
          target="_blank"
          rel="noreferrer"
          title={downloadLabel}
          aria-label={downloadLabel}
          onClick={(event) => event.stopPropagation()}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-white text-outline shadow-sm ring-1 ring-surface-container-high hover:bg-primary/10 hover:text-primary"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">download</span>
        </a>
      ) : null}
    </span>
  )
}

export default function SharedPerformanceLibrary({ showToast = () => {}, currentUser = null }) {
  const summaryInputRef = useRef(null)
  const contractInputRef = useRef(null)
  const attachmentInputRef = useRef(null)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [uploadingCategoryId, setUploadingCategoryId] = useState('')
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [previewFile, setPreviewFile] = useState(null)
  const [contractFiles, setContractFiles] = useState([])
  const [preview, setPreview] = useState(null)
  const [importForm, setImportForm] = useState({ categoryName: '', scene: '', powerRating: '', tags: '' })
  const [detail, setDetail] = useState(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [filters, setFilters] = useState({
    keyword: '',
    turbineModel: '',
    contractYear: '',
    deliveryYear: '',
    operationYear: '',
    status: 'enabled',
  })
  const [sort, setSort] = useState({ sortBy: 'updatedAt', sortOrder: 'desc' })
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteConfirmName, setDeleteConfirmName] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [attachmentPreview, setAttachmentPreview] = useState(null)
  const [attachmentPreviewLoading, setAttachmentPreviewLoading] = useState(false)
  const [attachmentPreviewError, setAttachmentPreviewError] = useState('')
  const pageSize = 20
  const sourceWorkspace = sourceWorkspaceFor(currentUser)
  const sourceMaterialsBasePath = workspaceRoute(sourceWorkspace, '/materials')
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const hasLoadedItemsRef = useRef(false)
  const sharedPerformanceItems = useMemo(() => [
    { key: 'raw', label: '原始素材', absolutePath: `${sourceMaterialsBasePath}/raw` },
    { key: 'wiki', label: 'Wiki', absolutePath: `${sourceMaterialsBasePath}/wiki` },
    ...(sourceWorkspace === 'tech'
      ? [{ key: 'certificates', label: '证书台账', absolutePath: `${sourceMaterialsBasePath}/certificates` }]
      : []),
    { key: 'performance', label: '业绩库', absolutePath: '/workspace/shared/materials/performance' },
  ], [sourceMaterialsBasePath, sourceWorkspace])

  const query = useMemo(() => ({ ...filters, ...sort, page, pageSize }), [filters, sort, page])

  const loadItems = useCallback(async () => {
    const initialLoad = !hasLoadedItemsRef.current
    if (initialLoad) {
      setLoading(true)
    } else {
      setRefreshing(true)
    }
    try {
      const payload = await performanceAPI.items(query)
      setItems(payload?.items || [])
      setTotal(Number(payload?.total || 0))
    } catch (error) {
      showToast(error?.message || '业绩库加载失败', 'error')
    } finally {
      hasLoadedItemsRef.current = true
      setLoading(false)
      setRefreshing(false)
    }
  }, [query, showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadItems()
    }, hasLoadedItemsRef.current ? 300 : 0)
    return () => clearTimeout(timer)
  }, [loadItems])

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
      const result = await performanceAPI.previewCategory(data)
      const nextPreview = result?.preview || null
      setPreviewFile(file)
      setContractFiles([])
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
    setContractFiles([])
    setPreview(null)
    setImportForm({ categoryName: '', scene: '', powerRating: '', tags: '' })
  }

  const updateImportForm = (key, value) => {
    setImportForm((prev) => ({ ...prev, [key]: value }))
  }

  const openContractChooser = () => {
    if (!contractInputRef.current) return
    contractInputRef.current.value = ''
    contractInputRef.current.click()
  }

  const addContractFiles = (event) => {
    const selected = Array.from(event.target.files || [])
    event.target.value = ''
    if (!selected.length) return
    setContractFiles((prev) => {
      const seen = new Set(prev.map((file) => `${file.name}|${file.size}`))
      const next = [...prev]
      selected.forEach((file) => {
        const key = `${file.name}|${file.size}`
        if (seen.has(key)) return
        seen.add(key)
        next.push(file)
      })
      return next
    })
  }

  const removeContractFile = (index) => {
    setContractFiles((prev) => prev.filter((_, position) => position !== index))
  }

  const confirmImport = async () => {
    if (!previewFile) return
    if (!importForm.categoryName.trim()) {
      showToast('请填写业绩类别名称', 'error')
      return
    }
    if (!contractFiles.length) {
      showToast('请选择合同附件：汇总表与合同需一次导入', 'error')
      return
    }
    const data = new FormData()
    data.append('file', previewFile, previewFile.name)
    contractFiles.forEach((file) => {
      data.append('contractFiles', file, file.name)
    })
    data.append('categoryName', importForm.categoryName.trim())
    data.append('scene', importForm.scene.trim())
    data.append('powerRating', importForm.powerRating.trim())
    data.append('tags', importForm.tags)
    data.append('scope', 'standard')
    data.append('reviewStatus', 'draft')
    setImporting(true)
    try {
      const result = await performanceAPI.importCategory(data)
      showToast(result?.message || '业绩包已导入')
      closePreview()
      await loadItems()
    } catch (error) {
      showToast(error?.message || '业绩包导入失败', 'error')
    } finally {
      setImporting(false)
    }
  }

  const openCategoryDetail = async (categoryId) => {
    if (!categoryId) return
    setDetailOpen(true)
    setDetail(null)
    setDetailLoading(true)
    try {
      const payload = await performanceAPI.category(categoryId)
      setDetail(payload || null)
    } catch (error) {
      showToast(error?.message || '业绩类别加载失败', 'error')
      setDetailOpen(false)
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetail = () => {
    setDetailOpen(false)
    setDetail(null)
    setDetailLoading(false)
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
      const result = await performanceAPI.uploadCategoryAttachment(uploadingCategoryId, data)
      showToast(result?.message || '合同附件已上传')
      await loadItems()
      if (detail?.item?.id === uploadingCategoryId) {
        const payload = await performanceAPI.category(uploadingCategoryId)
        setDetail(payload || null)
      }
    } catch (error) {
      showToast(error?.message || '合同附件上传失败', 'error')
    } finally {
      setUploadingAttachment(false)
      setUploadingCategoryId('')
    }
  }

  const toggleCategoryStatus = async (categoryItem) => {
    if (!categoryItem?.id) return
    const nextStatus = categoryItem.status === 'disabled' ? 'enabled' : 'disabled'
    const nextLabel = CATEGORY_STATUS_LABELS[nextStatus]
    if (!window.confirm(`确认${nextLabel}业绩类别：${categoryItem.name || categoryItem.id}？`)) return
    try {
      const result = await performanceAPI.updateCategoryStatus(categoryItem.id, { status: nextStatus })
      showToast(result?.message || `业绩类别已${nextLabel}`)
      await loadItems()
      if (detail?.item?.id === categoryItem.id) {
        const payload = await performanceAPI.category(categoryItem.id)
        setDetail(payload || null)
      }
    } catch (error) {
      showToast(error?.message || `业绩类别${nextLabel}失败`, 'error')
    }
  }

  const openDeleteDialog = (categoryItem) => {
    setDeleteTarget(categoryItem)
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
      const result = await performanceAPI.deleteCategory(deleteTarget.id, { confirmName: deleteConfirmName.trim() })
      showToast(result?.message || '业绩类别已删除')
      await loadItems()
      if (detail?.item?.id === deleteTarget.id) closeDetail()
      closeDeleteDialog()
    } catch (error) {
      showToast(error?.message || '业绩类别删除失败', 'error')
    } finally {
      setDeleting(false)
    }
  }

  const closeAttachmentPreview = () => {
    setAttachmentPreview(null)
    setAttachmentPreviewLoading(false)
    setAttachmentPreviewError('')
  }

  const previewCategoryAttachment = async (attachment) => {
    if (!attachment?.categoryId || !attachment?.id) return
    setAttachmentPreview({ fileName: attachment.fileName || '附件预览' })
    setAttachmentPreviewLoading(true)
    setAttachmentPreviewError('')
    try {
      const payload = await performanceAPI.previewCategoryAttachment(attachment.categoryId, attachment.id)
      setAttachmentPreview(payload)
    } catch (error) {
      setAttachmentPreviewError(error?.message || '附件预览加载失败')
    } finally {
      setAttachmentPreviewLoading(false)
    }
  }

  const previewItemAttachment = async (row, attachment) => {
    if (!row?.categoryId || !row?.id || !attachment?.id) return
    setAttachmentPreview({
      fileName: attachment.fileName || '项目合同附件',
    })
    setAttachmentPreviewError('')
    setAttachmentPreviewLoading(true)
    try {
      const payload = await performanceAPI.previewItemAttachment(row.categoryId, row.id, attachment.id)
      setAttachmentPreview({
        ...payload,
        fileUrl: payload?.fileUrl || performanceAPI.itemAttachmentUrl(row.categoryId, row.id, attachment.id),
      })
    } catch (error) {
      setAttachmentPreviewError(error?.message || '项目合同预览加载失败')
      setAttachmentPreview({
        fileName: attachment.fileName || '项目合同附件',
        previewMode: 'download',
        fileUrl: performanceAPI.itemAttachmentUrl(row.categoryId, row.id, attachment.id),
        message: '项目合同预览加载失败，请下载核对原件。',
      })
    } finally {
      setAttachmentPreviewLoading(false)
    }
  }

  const currentDetailItem = detail?.item
  const currentFields = currentDetailItem?.fieldSchema || []
  const visibleFields = currentFields.length ? currentFields : (preview?.fieldSchema || [])

  return (
    <main className="h-full min-h-0 overflow-hidden bg-surface text-on-surface">
      <input ref={summaryInputRef} type="file" accept=".docx" onChange={previewSummary} className="hidden" />
      <input ref={contractInputRef} type="file" accept=".doc,.docx" multiple onChange={addContractFiles} className="hidden" />
      <input ref={attachmentInputRef} type="file" accept=".doc,.docx" onChange={uploadAttachment} className="hidden" />
      <div className="flex h-full min-h-0 flex-col gap-3">
        <MaterialsViewSwitch
          active="performance"
          title="平台共用业绩库"
          basePath={sourceMaterialsBasePath}
          workspaceLabel="共用"
          workspaceIcon="database"
          items={sharedPerformanceItems}
        />

        <section className="rounded-lg border border-surface-container-high bg-surface-container-lowest p-3">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,0.9fr)_minmax(0,0.6fr)_minmax(0,0.6fr)_minmax(0,0.6fr)_7.5rem_auto]">
            <input value={filters.keyword} onChange={(event) => updateFilter('keyword', event.target.value)} placeholder="搜索项目/买方/型号/类别" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.turbineModel} onChange={(event) => updateFilter('turbineModel', event.target.value)} placeholder="型号，如 EW8.5-230" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.contractYear} onChange={(event) => updateFilter('contractYear', event.target.value)} placeholder="合同年" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.deliveryYear} onChange={(event) => updateFilter('deliveryYear', event.target.value)} placeholder="交货年" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <input value={filters.operationYear} onChange={(event) => updateFilter('operationYear', event.target.value)} placeholder="投运年" className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm" />
            <select value={filters.status} onChange={(event) => updateFilter('status', event.target.value)} className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-sm">
              {CATEGORY_STATUS_OPTIONS.map((option) => (
                <option key={option.label} value={option.value}>{option.label}</option>
              ))}
            </select>
            <button
              onClick={openSummaryChooser}
              disabled={previewing}
              className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-on-primary hover:brightness-95 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-base">upload_file</span>
              {previewing ? '解析中...' : '导入'}
            </button>
          </div>
        </section>

        <section className="relative min-h-0 flex-1 overflow-auto rounded-lg border border-surface-container-high bg-white">
          {loading && !items.length ? (
            <div className="p-6 text-sm text-on-surface-variant">加载中...</div>
          ) : !items.length ? (
            <div className="p-6 text-sm text-on-surface-variant">暂无业绩明细，点击「导入」上传汇总表与合同</div>
          ) : (
            <table className={`w-full min-w-[1240px] table-fixed text-left text-[13px] leading-5 transition-opacity ${refreshing ? 'opacity-60' : ''}`}>
              <colgroup>
                <col className="w-[22%]" />
                <col className="w-[17%]" />
                <col className="w-[9%]" />
                <col className="w-[6%]" />
                <col className="w-[8%]" />
                <col className="w-[8%]" />
                <col className="w-[20%]" />
                <col className="w-[10%]" />
              </colgroup>
              <thead className="sticky top-0 z-10 bg-surface-container-low text-xs text-on-surface-variant">
                <tr>
                  {SORTABLE_COLUMNS.map((column) => (
                    <th key={column.key} className="px-3 py-2.5">
                      <SortHeader columnKey={column.key} label={column.label} sortBy={sort.sortBy} sortOrder={sort.sortOrder} onSort={updateSort} />
                    </th>
                  ))}
                  <th className="px-3 py-2.5 text-xs font-semibold">数量/容量</th>
                  <th className="px-3 py-2.5 text-xs font-semibold">项目合同</th>
                  <th className="px-3 py-2.5">
                    <SortHeader columnKey="categoryName" label="所属类别" sortBy={sort.sortBy} sortOrder={sort.sortOrder} onSort={updateSort} />
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const modelLabel = compactList(row.turbineModels?.length ? row.turbineModels : [row.turbineModel])
                  return (
                    <tr key={row.id} className="group border-t border-surface-container-high align-top transition-colors hover:bg-surface-container-low">
                      <td className="px-3 py-2.5">
                        <div className="truncate font-semibold leading-5" title={row.projectName || '-'}>
                          {row.projectName || '-'}
                        </div>
                        {row.contactInfo ? (
                          <div className="mt-0.5 truncate text-xs leading-4 text-outline" title={row.contactInfo}>{row.contactInfo}</div>
                        ) : null}
                      </td>
                      <td className="truncate px-3 py-2.5" title={row.customerName || '-'}>{row.customerName || '-'}</td>
                      <td className="truncate px-3 py-2.5 text-on-surface-variant" title={modelLabel}>{modelLabel}</td>
                      <td className="px-3 py-2.5">{row.contractYear || '-'}</td>
                      <td className="px-3 py-2.5">
                        <div>{compactYears([row.deliveryYear], [row.operationYear])}</div>
                        {row.deliveryOrOperationTime ? (
                          <div className="mt-0.5 truncate text-xs leading-4 text-outline" title={row.deliveryOrOperationTime}>{row.deliveryOrOperationTime}</div>
                        ) : null}
                      </td>
                      <td className="truncate px-3 py-2.5" title={compactParts(row.contractQuantity, row.commissionedCapacityMw)}>
                        {compactParts(row.contractQuantity, row.commissionedCapacityMw) || '-'}
                      </td>
                      <td className="px-3 py-2.5">
                        {(row.attachments || []).length ? (
                          <div className="space-y-1">
                            {row.attachments.map((attachment) => {
                              const downloadUrl = performanceAPI.itemAttachmentUrl(row.categoryId, row.id, attachment.id)
                              return (
                                <div
                                  key={attachment.id}
                                  title={attachment.sourceTitle || attachment.fileName}
                                  className="group flex w-full items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-left text-xs leading-4 text-primary hover:bg-primary/15"
                                >
                                  <button
                                    type="button"
                                    onClick={() => previewItemAttachment(row, attachment)}
                                    className="min-w-0 flex-1 text-left"
                                  >
                                    <span className="block truncate">{attachment.fileName}</span>
                                    <span className="block truncate text-[11px] text-outline">
                                      {attachment.matchMethod === 'row_order' ? '按行匹配' : '项目名匹配'} · {attachment.matchConfidence || 0}%
                                    </span>
                                  </button>
                                  <AttachmentHoverActions
                                    downloadUrl={downloadUrl}
                                    onPreview={() => previewItemAttachment(row, attachment)}
                                  />
                                </div>
                              )
                            })}
                          </div>
                        ) : (
                          <span className="text-outline">未拆分</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <button
                          onClick={() => openCategoryDetail(row.categoryId)}
                          title={row.categoryName || row.categoryId}
                          className="block w-full truncate text-left text-primary hover:underline"
                        >
                          {row.categoryName || row.categoryId}
                        </button>
                        {row.categoryStatus === 'disabled' ? (
                          <span className="mt-1 inline-flex rounded-full bg-error-container/70 px-1.5 py-0.5 text-[11px] leading-4 text-error ring-1 ring-error/25">已停用</span>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {refreshing && items.length ? (
            <div className="pointer-events-none absolute inset-0 flex items-start justify-center bg-white/25 pt-4">
              <span className="rounded-full border border-outline-variant/60 bg-white px-3 py-1 text-xs font-medium text-on-surface-variant">正在刷新...</span>
            </div>
          ) : null}
        </section>

        <div className="flex items-center justify-between text-sm text-on-surface-variant">
          <span>共 {total} 条业绩明细</span>
          <div className="flex items-center gap-2">
            <button disabled={page <= 1} onClick={() => setPage((prev) => Math.max(1, prev - 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">上一页</button>
            <span>{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))} className="rounded-md bg-surface-container-high px-3 py-1.5 disabled:opacity-50">下一页</button>
          </div>
        </div>
      </div>

      {preview && (
        <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 transition-opacity">
          <div className="wizard-modal-surface flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
            <div className="flex items-center justify-between border-b border-surface-container-high px-5 py-4">
              <div>
                <h2 className="text-base font-semibold">导入业绩包</h2>
                <p className="mt-1 text-xs text-on-surface-variant">{preview.sourceFileName} · {preview.rowCount} 条明细 · 需同时上传合同附件</p>
              </div>
              <button onClick={closePreview} className="close-plain flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant hover:text-primary" aria-label="关闭">
                <span className="material-symbols-outlined text-base">close</span>
              </button>
            </div>
            <div className="min-h-0 overflow-auto p-5">
              <div className="grid gap-3 md:grid-cols-4">
                <label className="text-sm text-on-surface-variant md:col-span-2">类别名称<input value={importForm.categoryName} onChange={(event) => updateImportForm('categoryName', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant">场景<input value={importForm.scene} onChange={(event) => updateImportForm('scene', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant">功率<input value={importForm.powerRating} onChange={(event) => updateImportForm('powerRating', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
                <label className="text-sm text-on-surface-variant md:col-span-4">标签<input value={importForm.tags} onChange={(event) => updateImportForm('tags', event.target.value)} className="mt-1 h-10 w-full rounded-lg border-none bg-surface-container-highest px-3 text-sm text-on-surface" /></label>
              </div>

              <div className="mt-4 rounded-lg border border-surface-container-high bg-white p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold">合同附件 <span className="text-error">*</span></h3>
                    <p className="mt-0.5 text-xs text-on-surface-variant">汇总表与合同需一次导入；合同 Word 会按明细自动拆分绑定</p>
                  </div>
                  <button onClick={openContractChooser} className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs text-primary hover:bg-primary/15">选择合同文件</button>
                </div>
                {contractFiles.length ? (
                  <ul className="mt-2 space-y-1">
                    {contractFiles.map((file, index) => (
                      <li key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-2 rounded-md bg-surface-container-low px-2.5 py-1.5 text-xs">
                        <span className="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span>
                        <span className="shrink-0 text-outline">{sizeLabel(file.size) || '-'}</span>
                        <button
                          type="button"
                          onClick={() => removeContractFile(index)}
                          className="close-plain flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-on-surface-variant hover:text-error"
                          aria-label={`移除 ${file.name}`}
                        >
                          <span className="material-symbols-outlined text-sm">close</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="mt-2 rounded-md border border-dashed border-surface-container-high px-3 py-2 text-xs text-on-surface-variant">尚未选择合同文件，需至少一个才能导入</div>
                )}
              </div>

              {preview.summary ? (
                <div className="mt-4 rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">{preview.summary}</div>
              ) : null}

              <div className="mt-4 overflow-auto rounded-lg border border-surface-container-high bg-white">
                <table className="w-full min-w-[1220px] text-left text-xs">
                  <thead className="bg-surface-container-low text-on-surface-variant">
                    <tr>
                      <th className="px-3 py-2">系统提取型号</th>
                      <th className="px-3 py-2">合同年</th>
                      <th className="px-3 py-2">交货/投运年</th>
                      {(preview.fieldSchema || []).map((field) => (
                        <th key={field.key || field.label} className="px-3 py-2">{field.label || field.sourceHeader || field.key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows(preview.rows).map((row) => (
                      <tr key={row.rowIndex} className="border-t border-surface-container-high">
                        <td className="max-w-[16rem] truncate px-3 py-2" title={compactList(row.turbineModels)}>{compactList(row.turbineModels)}</td>
                        <td className="px-3 py-2">{row.contractYear || '-'}</td>
                        <td className="px-3 py-2">{compactYears([row.deliveryYear], [row.operationYear])}</td>
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
              <button
                onClick={confirmImport}
                disabled={importing || !contractFiles.length}
                title={contractFiles.length ? undefined : '请先选择合同附件'}
                className="rounded-lg bg-primary px-4 py-2 text-sm text-on-primary disabled:opacity-50"
              >
                {importing ? '导入中...' : '确认导入'}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="dialog-overlay fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4 transition-opacity">
          <div className="wizard-modal-surface w-full max-w-lg overflow-hidden rounded-xl border border-error/30 bg-surface-container-lowest animate-float-in">
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

      {detailOpen && (
        <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 transition-opacity">
          <div className="wizard-modal-surface flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
            <div className="flex items-center justify-between gap-3 border-b border-surface-container-high px-5 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold">{currentDetailItem?.name || '业绩类别'}</h2>
                <p className="mt-1 text-xs text-on-surface-variant">{compactParts(currentDetailItem?.scene, currentDetailItem?.powerRating, `${currentDetailItem?.itemCount || 0} 条明细`, CATEGORY_STATUS_LABELS[currentDetailItem?.status] || '')}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {currentDetailItem ? (
                  <>
                    <button
                      onClick={() => toggleCategoryStatus(currentDetailItem)}
                      className={`rounded-md px-2.5 py-1.5 text-xs ${currentDetailItem.status === 'disabled' ? 'bg-secondary-container text-on-secondary-container hover:bg-secondary-container/80' : 'bg-error-container/70 text-error ring-1 ring-error/25 hover:bg-error-container'}`}
                    >
                      {currentDetailItem.status === 'disabled' ? '启用' : '停用'}
                    </button>
                    <button
                      onClick={() => openDeleteDialog(currentDetailItem)}
                      className="rounded-md bg-error-container/70 px-2.5 py-1.5 text-xs text-error ring-1 ring-error/25 hover:bg-error-container"
                    >
                      删除
                    </button>
                  </>
                ) : null}
                <button onClick={closeDetail} className="close-plain flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant hover:text-primary" aria-label="关闭">
                  <span className="material-symbols-outlined text-base">close</span>
                </button>
              </div>
            </div>
            {detailLoading ? (
              <div className="flex min-h-[360px] items-center justify-center p-6 text-sm text-on-surface-variant">
                <div className="text-center">
                  <span className="material-symbols-outlined text-2xl text-primary">hourglass_empty</span>
                  <p className="mt-2">正在加载明细...</p>
                </div>
              </div>
            ) : (
              <div className="min-h-0 overflow-auto p-5">
                {currentDetailItem?.summary ? (
                  <div className="rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">{currentDetailItem.summary}</div>
                ) : null}

                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">原始附件</h3>
                    <button
                      onClick={() => chooseAttachmentFile(currentDetailItem)}
                      disabled={uploadingAttachment}
                      className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs text-primary hover:bg-primary/15 disabled:opacity-50"
                    >
                      {uploadingAttachment && uploadingCategoryId === currentDetailItem?.id ? '上传中...' : '补传/替换合同'}
                    </button>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    {(detail.attachments || []).length ? detail.attachments.map((attachment) => {
                      const downloadUrl = performanceAPI.categoryAttachmentUrl(attachment.categoryId, attachment.id)
                      return (
                        <div
                          key={attachment.id}
                          className="group flex items-center justify-between gap-3 rounded-lg border border-surface-container-high bg-white px-3 py-2 text-left text-sm hover:border-primary"
                        >
                          <button
                            type="button"
                            onClick={() => previewCategoryAttachment(attachment)}
                            className="min-w-0 flex-1 text-left"
                          >
                            <span className="block truncate font-medium text-primary">{attachment.fileName}</span>
                            <span className="mt-1 block truncate text-xs text-outline">{ATTACHMENT_LABELS[attachment.attachmentType] || attachment.attachmentType} · {sizeLabel(attachment.sizeBytes) || '-'}</span>
                          </button>
                          <AttachmentHoverActions
                            downloadUrl={downloadUrl}
                            onPreview={() => previewCategoryAttachment(attachment)}
                          />
                        </div>
                      )
                    }) : <div className="text-sm text-on-surface-variant">暂无原始附件</div>}
                  </div>
                </div>

                <div className="mt-4 overflow-auto rounded-lg border border-surface-container-high bg-white">
                  <table className="w-full min-w-[1480px] text-left text-xs">
                    <thead className="sticky top-0 bg-surface-container-low text-on-surface-variant">
                      <tr>
                        <th className="px-3 py-2">系统提取型号</th>
                        <th className="px-3 py-2">合同年</th>
                        <th className="px-3 py-2">交货/投运年</th>
                        <th className="px-3 py-2">项目合同</th>
                        {visibleFields.map((field) => (
                          <th key={field.key || field.label} className="px-3 py-2">{field.label || field.sourceHeader || field.key}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.rows || []).map((row) => (
                        <tr key={row.id} className="border-t border-surface-container-high">
                          <td className="max-w-[16rem] truncate px-3 py-2 align-top" title={compactList(row.turbineModels)}>{compactList(row.turbineModels)}</td>
                          <td className="px-3 py-2 align-top">{row.contractYear || '-'}</td>
                          <td className="px-3 py-2 align-top">{compactYears([row.deliveryYear], [row.operationYear])}</td>
                          <td className="min-w-[180px] max-w-[240px] px-3 py-2 align-top">
                            {(row.attachments || []).length ? (
                              <div className="space-y-1">
                                {row.attachments.map((attachment) => {
                                  const downloadUrl = performanceAPI.itemAttachmentUrl(row.categoryId, row.id, attachment.id)
                                  return (
                                    <div
                                      key={attachment.id}
                                      title={attachment.sourceTitle || attachment.fileName}
                                      className="group flex w-full items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-left text-[11px] leading-4 text-primary hover:bg-primary/15"
                                    >
                                      <button
                                        type="button"
                                        onClick={() => previewItemAttachment(row, attachment)}
                                        className="min-w-0 flex-1 text-left"
                                      >
                                        <span className="block truncate">{attachment.fileName}</span>
                                        <span className="block truncate text-[10px] text-outline">
                                          {attachment.matchMethod === 'row_order' ? '按行匹配' : '项目名匹配'} · {attachment.matchConfidence || 0}%
                                        </span>
                                      </button>
                                      <AttachmentHoverActions
                                        downloadUrl={downloadUrl}
                                        onPreview={() => previewItemAttachment(row, attachment)}
                                      />
                                    </div>
                                  )
                                })}
                              </div>
                            ) : (
                              <span className="text-outline">未拆分</span>
                            )}
                          </td>
                          {visibleFields.map((field) => {
                            const label = field.sourceHeader || field.label
                            const value = row.values?.[label] || '-'
                            return <td key={field.key || field.label} className="max-w-[18rem] truncate px-3 py-2 align-top" title={value}>{value}</td>
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

      {attachmentPreview && (
        <div className="dialog-overlay fixed inset-0 z-[70] bg-black/45 p-3 sm:p-4">
          <div className="mx-auto flex h-full w-full max-w-[92vw] flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-surface-container-high px-5 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-on-surface">{attachmentPreview.fileName || '附件预览'}</h2>
                <p className="mt-1 text-xs text-on-surface-variant">业绩附件在线预览</p>
              </div>
              <button onClick={closeAttachmentPreview} className="close-plain flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant hover:text-primary" aria-label="关闭预览">
                <span className="material-symbols-outlined text-base">close</span>
              </button>
            </div>
            <div className="min-h-0 flex-1 bg-surface-container-low p-3">
              {attachmentPreviewLoading ? (
                <div className="flex h-full items-center justify-center text-sm text-on-surface-variant">正在加载附件预览...</div>
              ) : attachmentPreview?.previewMode === 'images' ? (
                <div className="flex h-full min-h-0 flex-col gap-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-container-high bg-white px-3 py-2 text-xs text-on-surface-variant">
                    <span>{attachmentPreview.message || `共 ${attachmentPreview.images?.length || 0} 页合同图片`}</span>
                    {attachmentPreview.fileUrl ? (
                      <a
                        href={attachmentPreview.fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex h-8 items-center gap-1 rounded-md bg-primary px-3 text-xs font-medium text-on-primary hover:opacity-90"
                      >
                        <span className="material-symbols-outlined text-sm">download</span>
                        下载原件
                      </a>
                    ) : null}
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-surface-container-high bg-surface-container px-3 py-4">
                    <div className="flex flex-col gap-4">
                      {(attachmentPreview.images || []).map((image) => (
                        <figure key={`${image.index}-${image.name}`} className="overflow-hidden rounded-lg border border-surface-container-high bg-white shadow-sm">
                          <div className="border-b border-surface-container-high px-3 py-2 text-xs text-on-surface-variant">
                            第 {image.index} 页 · {image.name}
                          </div>
                          <img
                            src={image.dataUrl}
                            alt={`合同第 ${image.index} 页`}
                            className="block h-auto w-full"
                            loading="lazy"
                          />
                        </figure>
                      ))}
                    </div>
                  </div>
                </div>
              ) : attachmentPreview?.previewMode === 'download' ? (
                <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-surface-container-high bg-white px-4 text-center text-sm text-on-surface-variant">
                  <div>
                    <span className="material-symbols-outlined text-3xl text-primary">download</span>
                    <p className="mt-3">{attachmentPreview.message || '该附件暂时无法在线预览。'}</p>
                    {attachmentPreview.fileUrl ? (
                      <a
                        href={attachmentPreview.fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-4 inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:opacity-90"
                      >
                        下载附件
                      </a>
                    ) : null}
                  </div>
                </div>
              ) : attachmentPreview?.onlyoffice?.fileUrl && !attachmentPreviewError ? (
                <OnlyOfficeEmbed
                  session={attachmentPreview.onlyoffice}
                  mode="view"
                  className="h-full w-full rounded-lg border border-surface-container-high bg-white"
                  onError={(message) => setAttachmentPreviewError(message || 'OnlyOffice 附件预览加载失败')}
                />
              ) : (
                <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-surface-container-high bg-white px-4 text-center text-sm text-on-surface-variant">
                  {attachmentPreviewError || '该附件暂时无法在线预览。'}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
