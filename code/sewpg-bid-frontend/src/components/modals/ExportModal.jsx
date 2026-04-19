import { useEffect, useMemo, useState } from 'react'
import { exportAPI } from '../../api'

const formatDate = () => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}${m}${d}`
}

const toHardBlockMessage = (error) => {
  if (!error) return ''
  const code = error.code || ''
  const map = {
    EXPORT_BLOCKED_BY_COVERAGE: '存在未覆盖评分项（红项），已触发硬拦截，禁止导出。',
    EXPORT_NAME_REQUIRED: '导出文件名不能为空。',
    EXPORT_NAME_INVALID: '导出文件名包含非法字符，请仅使用中英文、数字、下划线或中划线。',
    EXPORT_WARNING_NOT_CONFIRMED: '请先确认已阅读导出注意事项后再继续。',
  }
  return map[code] || error.message || '导出失败，请稍后重试。'
}

export default function ExportModal({ projectId, onClose, onExport }) {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState('docx')
  const [exportName, setExportName] = useState('')
  const [nameError, setNameError] = useState('')
  const [warningConfirmed, setWarningConfirmed] = useState(false)
  const [hardBlockError, setHardBlockError] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(true)
      setError('')
      setHardBlockError('')
      exportAPI.check(projectId)
        .then((d) => {
          setData(d)
          setExportName(d?.suggestedFileName || `投标文件_${projectId}_${formatDate()}`)
        })
        .catch((e) => {
          setError(e?.message || '导出前校验失败')
        })
        .finally(() => {
          setLoading(false)
        })
    }, 0)

    return () => clearTimeout(timer)
  }, [projectId])

  const blockingChecks = (data?.checks || []).filter((check) => !check.passed)
  const hasBlockingIssue = blockingChecks.length > 0
  const hasWarnings = (data?.warnings || []).length > 0

  const validateExportName = (value) => {
    const trimmed = value.trim()
    if (!trimmed) return '导出文件名不能为空'
    if (trimmed.length > 80) return '文件名过长，请控制在 80 字符以内'
    if (!/^[\w\u4e00-\u9fa5-]+$/.test(trimmed)) {
      return '仅支持中英文、数字、下划线(_)和中划线(-)'
    }
    return ''
  }

  const canExport = useMemo(() => {
    if (loading || exporting || !!error || hasBlockingIssue) return false
    if (validateExportName(exportName)) return false
    if (hasWarnings && !warningConfirmed) return false
    return true
  }, [loading, exporting, error, hasBlockingIssue, exportName, hasWarnings, warningConfirmed])

  const handleExport = async () => {
    if (loading || !!error || hasBlockingIssue) return

    const validationMessage = validateExportName(exportName)
    if (validationMessage) {
      setNameError(validationMessage)
      return
    }
    setNameError('')

    if (hasWarnings && !warningConfirmed) {
      setHardBlockError('请先确认已阅读导出注意事项')
      return
    }

    setHardBlockError('')
    setExporting(true)
    try {
      const res = await exportAPI.doExport(projectId, {
        format: selectedFormat,
        fileName: exportName.trim(),
        warningConfirmed,
      })
      onExport(res.fileUrl, res)
    } catch (e) {
      console.error(e)
      setHardBlockError(toHardBlockMessage(e))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content w-full max-w-xl animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-container-high">
          <h2 className="text-xl font-headline font-bold text-on-surface">打包导出标书</h2>
          <button onClick={onClose} className="text-on-surface-variant hover:text-primary transition-colors">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="p-6 flex flex-col gap-6">
          {/* Checks and Warnings */}
          {loading ? (
            <div className="animate-shimmer w-full h-32 rounded-lg"></div>
          ) : error ? (
            <div className="bg-error-container/20 border border-error/20 rounded-lg p-4 text-sm text-error">
              {error}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div>
                <h3 className="text-sm font-semibold text-on-surface flex items-center gap-2 mb-3">
                  <span className="material-symbols-outlined text-sm">fact_check</span>
                  导出前校验
                </h3>
                <div className="flex flex-col gap-2">
                  {data?.checks?.map((check, i) => (
                    <div key={i} className="flex items-start gap-2 bg-surface-container-low p-3 rounded-lg text-sm">
                      <span className={`material-symbols-outlined text-sm mt-0.5 ${check.passed ? 'text-secondary' : 'text-error'}`} style={{ fontVariationSettings: "'FILL' 1" }}>
                        {check.passed ? 'check_circle' : 'error'}
                      </span>
                      <span className="text-on-surface-variant">{check.label}</span>
                    </div>
                  ))}
                </div>
              </div>

              {hasBlockingIssue && (
                <div className="bg-error-container/20 border border-error/20 rounded-lg p-4 flex gap-3 items-start">
                  <span className="material-symbols-outlined text-error mt-0.5">block</span>
                  <div>
                    <h4 className="text-sm font-semibold text-error mb-1">存在阻塞项，禁止导出</h4>
                    <ul className="text-sm text-on-error-container list-disc ml-4 space-y-1">
                      {blockingChecks.map((item, index) => (
                        <li key={index}>{item.label}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {hasWarnings && (
                <div className="bg-tertiary-fixed border border-tertiary/20 rounded-lg p-4 flex gap-3 items-start">
                  <span className="material-symbols-outlined text-tertiary mt-0.5">warning</span>
                  <div className="w-full">
                    <h4 className="text-sm font-semibold text-on-tertiary-fixed mb-1">注意事项</h4>
                    <ul className="text-sm text-on-tertiary-fixed-variant list-disc ml-4 space-y-1 mb-3">
                      {data.warnings.map((w, i) => <li key={i}>{w.label}</li>)}
                    </ul>
                    <label className="flex items-center gap-2 text-xs text-on-tertiary-fixed-variant cursor-pointer">
                      <input
                        type="checkbox"
                        checked={warningConfirmed}
                        onChange={(event) => setWarningConfirmed(event.target.checked)}
                      />
                      我已阅读并确认以上导出风险
                    </label>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Format Selection */}
          <div>
            <h3 className="text-sm font-semibold text-on-surface mb-3">选择导出格式</h3>
            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={() => setSelectedFormat('docx')}
                className={`p-4 rounded-xl border-2 flex flex-col items-center gap-2 transition-all ${
                  selectedFormat === 'docx' ? 'border-primary bg-primary/5 text-primary' : 'border-surface-container-high bg-surface-container-lowest text-on-surface-variant hover:border-outline-variant/30'
                }`}
              >
                <div className={`w-12 h-12 rounded-full flex items-center justify-center ${selectedFormat === 'docx' ? 'bg-primary text-white' : 'bg-surface-container-high'}`}>
                  <span className="material-symbols-outlined">description</span>
                </div>
                <span className="text-sm font-bold">Word 文档</span>
                <span className="text-xs opacity-70">(.docx) 可编辑</span>
              </button>
              <button
                onClick={() => setSelectedFormat('pdf')}
                className={`p-4 rounded-xl border-2 flex flex-col items-center gap-2 transition-all ${
                  selectedFormat === 'pdf' ? 'border-error bg-error-container/20 text-error' : 'border-surface-container-high bg-surface-container-lowest text-on-surface-variant hover:border-outline-variant/30'
                }`}
              >
                <div className={`w-12 h-12 rounded-full flex items-center justify-center ${selectedFormat === 'pdf' ? 'bg-error text-white' : 'bg-surface-container-high'}`}>
                  <span className="material-symbols-outlined">picture_as_pdf</span>
                </div>
                <span className="text-sm font-bold">PDF 文档</span>
                <span className="text-xs opacity-70">(.pdf) 用于打印和归档</span>
              </button>
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-on-surface mb-2">导出文件名（必填）</h3>
            <input
              value={exportName}
              onChange={(event) => {
                setExportName(event.target.value)
                if (nameError) setNameError('')
              }}
              onBlur={() => setNameError(validateExportName(exportName))}
              placeholder="请输入导出文件名"
              className={`w-full h-11 px-3 rounded-lg border text-sm bg-surface-container-lowest text-on-surface focus:outline-none focus:ring-2 ${
                nameError ? 'border-error focus:ring-error/30' : 'border-outline-variant focus:ring-primary/30'
              }`}
            />
            <div className="mt-2 text-xs text-outline">最终文件：{(exportName || '未命名')}.{selectedFormat}</div>
            {nameError && <div className="mt-1 text-xs text-error">{nameError}</div>}
          </div>

          {hardBlockError && (
            <div className="bg-error-container/20 border border-error/30 rounded-lg p-3 text-sm text-error flex items-start gap-2">
              <span className="material-symbols-outlined text-sm mt-0.5">gpp_bad</span>
              <span>{hardBlockError}</span>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-surface-container-high flex justify-end gap-3 bg-surface-container-low rounded-b-xl">
          <button onClick={onClose} className="px-5 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors">
            取消
          </button>
          <button
            onClick={handleExport}
            disabled={!canExport}
            title={hasBlockingIssue ? '请先处理所有阻塞项后再导出' : ''}
            className="px-6 py-2.5 bg-gradient-to-r from-primary to-primary-container text-on-primary font-semibold rounded-lg hover:shadow-lg shadow-primary/20 transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {exporting ? (
              <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
            ) : (
              <span className="material-symbols-outlined text-sm">download</span>
            )}
            {exporting ? '导出中...' : hasBlockingIssue ? '存在阻塞项，无法导出' : '确认导出'}
          </button>
        </div>
      </div>
    </div>
  )
}
