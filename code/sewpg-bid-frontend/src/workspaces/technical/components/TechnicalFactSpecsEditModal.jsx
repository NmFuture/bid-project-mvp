import { useEffect, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import Button from '../../../components/ui/Button'
import { Dialog, DialogFooter, DialogHeader } from '../../../components/ui/Dialog'

// 列直接对应 spec 字段，不是 Excel 模板表头的镜像——Excel 清单现为
// 序号/类型/文件夹/文件名/占位符内容/引用文件，字段名由占位符正文剥离得出，
// 与这里的编辑列不是一一对应关系。key/sourceKind 等派生字段不在界面暴露，
// 保存时按导入解析器（technical_fact_spec_import.py）同款规则自动推导。
// table-fixed 按百分比分摊弹窗宽度：序号/操作收紧，长文本列多分
const COLUMNS = [
  { field: 'seq', label: '序号', type: 'number', width: 'w-12' },
  { field: 'targetFile', label: '待填写文件', type: 'multiline', width: 'w-[22%]' },
  { field: 'placeholder', label: '原占位符位置', width: 'w-[13%]' },
  { field: 'label', label: '实际要填写的字段', required: true, width: 'w-[15%]' },
  { field: 'note', label: '必要说明', type: 'multiline', width: 'w-[13%]' },
  { field: 'reviewLabel', label: '复核', type: 'multiline', width: 'w-[15%]' },
  { field: 'referenceFile', label: '来源文件', type: 'multiline', width: 'w-[16%]' },
]

const CELL_INPUT_CLASS =
  'h-8 w-full rounded border border-transparent bg-transparent px-1.5 text-xs text-on-surface transition-colors hover:border-outline-variant/70 focus:border-primary focus:bg-white focus:outline-none'
const CELL_TEXTAREA_CLASS =
  'w-full resize-y rounded border border-transparent bg-transparent px-1.5 py-1 text-xs leading-5 text-on-surface transition-colors hover:border-outline-variant/70 focus:border-primary focus:bg-white focus:outline-none'

let rowSeq = 0
const nextRowId = () => {
  rowSeq += 1
  return `row-${rowSeq}`
}

// —— 以下派生规则镜像后端 technical_fact_spec_import.py，改动时需同步 ——

// normalize_key：去空白、全角括号转半角、去常见标点
const normalizeKey = (text) =>
  String(text || '')
    .replace(/\s+/g, '')
    .replace(/（/g, '(')
    .replace(/）/g, ')')
    .replace(/[，,、;；:：/\\\-—_]+/g, '')
    .toLowerCase()

const SOURCE_KIND_RULES = [
  ['招标文件', 'tender'],
  ['项目定制', 'material'],
  ['认证证书', 'cert'],
  ['平台输入', 'platform'],
  ['自动生成', 'derived'],
]

// classify_source：整格留空=template（模板占位不进取数）；「/」=unspecified；按前缀归类
const classifySource = (referenceFile) => {
  const ref = String(referenceFile || '').trim()
  if (!ref) return 'template'
  if (ref === '/') return 'unspecified'
  for (const [prefix, kind] of SOURCE_KIND_RULES) {
    if (ref.startsWith(prefix)) return kind
  }
  return 'material'
}

const toEditRow = (spec, index) => ({
  _id: nextRowId(),
  seq: Number.isFinite(Number(spec?.seq)) ? Number(spec.seq) : index + 1,
  targetFile: String(spec?.targetFile || ''),
  placeholder: String(spec?.placeholder || ''),
  label: String(spec?.label || ''),
  note: String(spec?.note || ''),
  reviewLabel: String(spec?.reviewLabel || ''),
  referenceFile: String(spec?.referenceFile || ''),
  // 界面不展示但需在保存时保留的字段（aliases 暂不支持在弹窗编辑，原样带回）
  aliases: Array.isArray(spec?.aliases) ? spec.aliases : [],
})

const createEmptyRow = (index) => toEditRow({ seq: index + 1 }, index)

const toPayloadSpec = (row, index) => {
  const label = row.label.trim()
  const targetFile = row.targetFile.trim()
  const note = row.note.trim()
  const referenceFile = row.referenceFile.trim()
  const sourceKind = classifySource(referenceFile)
  return {
    seq: Number.isFinite(Number(row.seq)) && Number(row.seq) > 0 ? Math.trunc(Number(row.seq)) : index + 1,
    key: normalizeKey(label),
    label,
    reviewLabel: row.reviewLabel.trim(),
    targetFile,
    // sourceFile 语义同 targetFile（待填写目标文件），与导入产物保持一致
    sourceFile: targetFile,
    placeholder: row.placeholder.trim(),
    note,
    referenceFile,
    valueRequired: sourceKind !== 'template',
    sourceKind,
    aliases: row.aliases,
  }
}

// 事实表清单在线编辑：按 spec 字段整表行编辑，保存时整表 PUT 回后端；
// key/来源类别等派生字段按导入规则自动推导。走的不是 Excel 解析路径。
export default function TechnicalFactSpecsEditModal({ onClose, onSaved, showToast = () => {} }) {
  const [rows, setRows] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)

  const loadRows = async () => {
    setLoadError('')
    setRows(null)
    try {
      const payload = await technicalMaterialsAPI.rules.factSpecsRows()
      const specs = Array.isArray(payload?.specs) ? payload.specs : []
      setRows(specs.map(toEditRow))
    } catch (e) {
      setLoadError(e?.message || '事实表清单加载失败')
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      loadRows()
    }, 0)
    return () => clearTimeout(timer)
  }, [])

  const updateRow = (rowId, field, value) => {
    setRows((prev) => prev.map((row) => (row._id === rowId ? { ...row, [field]: value } : row)))
  }

  const addRow = () => {
    setRows((prev) => [...(prev || []), createEmptyRow((prev || []).length)])
  }

  const removeRow = (rowId) => {
    setRows((prev) => prev.filter((row) => row._id !== rowId))
  }

  const handleSave = async () => {
    if (!rows || saving) return
    const invalidIndex = rows.findIndex((row) => !row.label.trim())
    if (invalidIndex >= 0) {
      showToast(`第 ${invalidIndex + 1} 行的「实际要填写的字段」不能为空`, 'error')
      return
    }
    setSaving(true)
    try {
      const specs = rows.map(toPayloadSpec)
      await technicalMaterialsAPI.rules.saveFactSpecsRows(specs)
      showToast(`已保存 ${specs.length} 个字段，全局事实表清单已更新`)
      onSaved?.()
      onClose?.()
    } catch (e) {
      showToast(e?.message || '事实表清单保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={saving ? undefined : onClose} size="full">
      <DialogHeader onClose={saving ? undefined : onClose}>
        <h3 className="text-lg font-headline font-semibold text-on-surface">编辑项目事实表清单（全局）</h3>
        <p className="mt-1 text-xs text-outline">
          按事实表字段逐行编辑，全局一份、所有技术标项目共用，保存后整表生效。来源文件决定取数方式：招标文件 / 项目定制 / 认证证书 / 平台输入 / 自动生成，留空表示模板占位不取数。
        </p>
      </DialogHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        {loadError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
            <p className="text-sm text-error">{loadError}</p>
            <Button type="button" size="sm" variant="quiet" onClick={loadRows}>
              重试
            </Button>
          </div>
        ) : rows === null ? (
          <p className="p-6 text-sm text-outline">正在加载事实表清单...</p>
        ) : (
          <table className="w-full table-fixed border-collapse text-xs">
            <thead className="sticky top-0 z-10">
              <tr>
                {COLUMNS.map((column) => (
                  <th
                    key={column.field}
                    className={`whitespace-nowrap border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-left font-semibold text-on-surface-variant ${column.width}`}
                  >
                    {column.label}
                    {column.required ? <span className="ml-0.5 text-error">*</span> : null}
                  </th>
                ))}
                <th className="sticky right-0 w-14 whitespace-nowrap border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-center font-semibold text-on-surface-variant">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => {
                // sticky 操作列需要自带底色（bg-inherit 无法透出斑马纹），与 tr 的奇偶底色保持一致
                const rowBg = rowIndex % 2 === 0 ? 'bg-surface-container-lowest' : 'bg-surface-container-low/40'
                return (
                <tr key={row._id} className="odd:bg-surface-container-lowest even:bg-surface-container-low/40">
                  {COLUMNS.map((column) => (
                    <td key={column.field} className="border-b border-outline-variant/30 px-1 py-0.5 align-top">
                      {column.type === 'multiline' ? (
                        <textarea
                          rows={2}
                          className={CELL_TEXTAREA_CLASS}
                          value={row[column.field]}
                          onChange={(event) => updateRow(row._id, column.field, event.target.value)}
                          aria-label={`${column.label}（第 ${rowIndex + 1} 行）`}
                        />
                      ) : (
                        <input
                          type="text"
                          className={CELL_INPUT_CLASS}
                          value={row[column.field]}
                          onChange={(event) => updateRow(row._id, column.field, event.target.value)}
                          aria-label={`${column.label}（第 ${rowIndex + 1} 行）`}
                        />
                      )}
                    </td>
                  ))}
                  <td className={`sticky right-0 border-b border-outline-variant/30 px-1 py-0.5 text-center align-top ${rowBg}`}>
                    <button
                      type="button"
                      className="inline-flex h-7 items-center rounded px-2 text-xs font-medium text-error hover:bg-error/10"
                      onClick={() => removeRow(row._id)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
                )
              })}
              {rows.length ? null : (
                <tr>
                  <td colSpan={COLUMNS.length + 1} className="px-3 py-6 text-center text-outline">
                    暂无字段，点击下方「新增行」开始维护。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
      <DialogFooter>
        <div className="mr-auto flex items-center gap-3">
          <Button type="button" size="sm" variant="quiet" onClick={addRow} disabled={rows === null || saving}>
            新增行
          </Button>
          {rows ? <span className="text-xs text-outline">共 {rows.length} 行</span> : null}
        </div>
        <Button type="button" size="sm" variant="quiet" onClick={onClose} disabled={saving}>
          取消
        </Button>
        <Button type="button" size="sm" variant="primary" onClick={handleSave} disabled={rows === null || saving}>
          {saving ? '保存中...' : '保存'}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
