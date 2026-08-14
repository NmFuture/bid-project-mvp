import { useEffect, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import Button from '../../../components/ui/Button'
import { Dialog, DialogFooter, DialogHeader } from '../../../components/ui/Dialog'

// 来源列表在编辑态用「、」分隔的文本承载，保存前拆回数组（与 Excel 导出口径一致）。
// table-fixed 按百分比分摊弹窗宽度：表格名列略窄，三个来源列均分剩余空间。
const SOURCE_COLUMNS = [
  { field: 'projectSourcesText', label: '项目定制来源', width: 'w-[24%]' },
  { field: 'standardSourcesText', label: '标准文件来源', width: 'w-[24%]' },
  { field: 'otherSourcesText', label: '其他来源', width: 'w-[24%]' },
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

const joinSources = (list) => (Array.isArray(list) ? list : []).filter(Boolean).join('、')

const toEditRow = (row) => ({
  _id: nextRowId(),
  tableTitle: String(row?.tableTitle || ''),
  projectSourcesText: joinSources(row?.projectSources),
  standardSourcesText: joinSources(row?.standardSources),
  otherSourcesText: joinSources(row?.otherSources),
})

const createEmptyRow = () =>
  toEditRow({ tableTitle: '', projectSources: [], standardSources: [], otherSources: [] })

const splitSources = (text) =>
  String(text || '')
    .split(/[、,，;；]/)
    .map((item) => item.trim())
    .filter(Boolean)

const toPayloadRow = (row) => ({
  tableTitle: row.tableTitle.trim(),
  projectSources: splitSources(row.projectSourcesText),
  standardSources: splitSources(row.standardSourcesText),
  otherSources: splitSources(row.otherSourcesText),
})

// 附表填写规则在线编辑：按客户维护，整表行编辑（新增/删除/逐格修改），保存时整表 PUT 回后端。
export default function TechnicalAppendixRulesEditModal({ customerName, onClose, onSaved, showToast = () => {} }) {
  const [rows, setRows] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)

  const loadRows = async () => {
    setLoadError('')
    setRows(null)
    try {
      const payload = await technicalMaterialsAPI.rules.appendixMatrixRows(customerName)
      const list = Array.isArray(payload?.rows) ? payload.rows : []
      setRows(list.map(toEditRow))
    } catch (e) {
      setLoadError(e?.message || '附表填写规则加载失败')
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      loadRows()
    }, 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const updateRow = (rowId, field, value) => {
    setRows((prev) => prev.map((row) => (row._id === rowId ? { ...row, [field]: value } : row)))
  }

  const addRow = () => {
    setRows((prev) => [...(prev || []), createEmptyRow()])
  }

  const removeRow = (rowId) => {
    setRows((prev) => prev.filter((row) => row._id !== rowId))
  }

  const handleSave = async () => {
    if (!rows || saving) return
    const invalidIndex = rows.findIndex((row) => !row.tableTitle.trim())
    if (invalidIndex >= 0) {
      showToast(`第 ${invalidIndex + 1} 行的「表格/附表」不能为空`, 'error')
      return
    }
    setSaving(true)
    try {
      const payloadRows = rows.map(toPayloadRow)
      await technicalMaterialsAPI.rules.saveAppendixMatrixRows(customerName, payloadRows)
      showToast(`已保存 ${payloadRows.length} 条规则，已同步到「${customerName}」名下项目的缺口识别`)
      onSaved?.()
      onClose?.()
    } catch (e) {
      showToast(e?.message || '附表填写规则保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={saving ? undefined : onClose} size="full">
      <DialogHeader onClose={saving ? undefined : onClose}>
        <h3 className="text-lg font-headline font-semibold text-on-surface">编辑附表填写规则（{customerName}）</h3>
        <p className="mt-1 text-xs text-outline">
          每个客户一份，该客户名下项目缺口识别时自动套用。来源多个值用「、」分隔；保存后整表覆盖该客户规则。
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
          <p className="p-6 text-sm text-outline">正在加载附表填写规则...</p>
        ) : (
          <table className="w-full table-fixed border-collapse text-xs">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className="w-[22%] whitespace-nowrap border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-left font-semibold text-on-surface-variant">
                  表格/附表<span className="ml-0.5 text-error">*</span>
                </th>
                {SOURCE_COLUMNS.map((column) => (
                  <th
                    key={column.field}
                    className={`whitespace-nowrap border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-left font-semibold text-on-surface-variant ${column.width}`}
                  >
                    {column.label}
                  </th>
                ))}
                <th className="w-14 whitespace-nowrap border-b border-outline-variant/60 bg-surface-container-low px-2 py-2 text-center font-semibold text-on-surface-variant">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row._id} className="odd:bg-surface-container-lowest even:bg-surface-container-low/40">
                  <td className="border-b border-outline-variant/30 px-1 py-0.5 align-top">
                    <input
                      type="text"
                      className={CELL_INPUT_CLASS}
                      value={row.tableTitle}
                      onChange={(event) => updateRow(row._id, 'tableTitle', event.target.value)}
                    />
                  </td>
                  {SOURCE_COLUMNS.map((column) => (
                    <td key={column.field} className="border-b border-outline-variant/30 px-1 py-0.5 align-top">
                      <textarea
                        rows={2}
                        className={CELL_TEXTAREA_CLASS}
                        value={row[column.field]}
                        onChange={(event) => updateRow(row._id, column.field, event.target.value)}
                      />
                    </td>
                  ))}
                  <td className="border-b border-outline-variant/30 px-1 py-0.5 text-center">
                    <button
                      type="button"
                      className="inline-flex h-7 items-center rounded px-2 text-xs font-medium text-error hover:bg-error/10"
                      onClick={() => removeRow(row._id)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length ? null : (
                <tr>
                  <td colSpan={SOURCE_COLUMNS.length + 2} className="px-3 py-6 text-center text-outline">
                    暂无规则，点击下方「新增行」开始维护。
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
