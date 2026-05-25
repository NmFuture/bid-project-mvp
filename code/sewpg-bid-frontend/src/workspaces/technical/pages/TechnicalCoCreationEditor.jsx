import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { technicalDocumentAPI, technicalProjectsAPI } from '../../../api'
import { PageError, PageLoading } from '../components/TechnicalPageState'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import Button from '../../../components/ui/Button'

const FONT_OPTIONS = {
  zh: ['等线', '宋体', '仿宋', '黑体', '楷体', '微软雅黑', '方正仿宋_GBK', '方正小标宋_GBK'],
  en: ['Times New Roman', 'Arial', 'Calibri', 'Cambria', 'Georgia'],
}

const technicalFormatPresets = [
  {
    key: 'standard',
    label: '标准版',
    description: '统一标题、正文、表格、目录、页眉和分页。',
  },
  {
    key: 'custom',
    label: '自定义格式',
    description: '按技术标要求设置字体、字号、页边距和目录。',
  },
]

const triggerDownload = (url, fileName) => {
  if (!url) return false
  const link = document.createElement('a')
  link.href = url
  link.download = fileName || ''
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  return true
}

export default function TechnicalCoCreationEditor({ showToast }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [project, setProject] = useState(null)
  const [finalData, setFinalData] = useState(null)
  const [fallbackContent, setFallbackContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [savingFallback, setSavingFallback] = useState(false)
  const [pdfPreparing, setPdfPreparing] = useState(false)
  const [formatPreset, setFormatPreset] = useState('standard')
  const [formatApplying, setFormatApplying] = useState('')
  const [customFormat, setCustomFormat] = useState({
    bodyZhFont: '等线',
    bodyEnFont: 'Times New Roman',
    bodySizePt: 12,
    bodyLineSpacing: 1.5,
    bodyFirstLineIndentChars: 2,
    heading1SizePt: 15,
    heading2SizePt: 14,
    heading3SizePt: 12,
    pageTopCm: 2.54,
    pageBottomCm: 2.54,
    pageLeftCm: 3.18,
    pageRightCm: 3.18,
    tableZhFont: '宋体',
    tableSizePt: 10.5,
    tableLineSpacing: 1,
    insertToc: true,
    tocPageBreakAfter: true,
    headerTextTemplate: '{projectName}技术标投标文件',
  })

  const loadDocument = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, projectPayload, finalPayload] = await Promise.all([
        technicalDocumentAPI.get(id),
        technicalProjectsAPI.get(id).catch(() => null),
        technicalDocumentAPI.final(id).catch(() => null),
      ])
      setData(payload)
      setProject(projectPayload)
      setFinalData(finalPayload)
      setFallbackContent(payload?.fallback?.content || '')
      setOnlyofficeError('')
    } catch (e) {
      setError(e?.message || '技术标共创文档加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadDocument()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadDocument])

  const hasOnlyOfficeSession = Boolean(data?.onlyoffice?.fileUrl && data?.onlyoffice?.callbackUrl)
  const useFallbackEditor = !hasOnlyOfficeSession || Boolean(onlyofficeError)
  const projectName = project?.name || data?.projectName || id
  const fileName = finalData?.fileName || data?.fileName || '技术标投标文件.docx'

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await technicalDocumentAPI.save(id, { content })
      setData(response?.payload || data)
      showToast?.('技术标文档已保存并回写')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const handlePreparePdf = async () => {
    if (pdfPreparing) return
    setPdfPreparing(true)
    try {
      const response = await technicalDocumentAPI.finalPdf(id)
      const downloaded = triggerDownload(response?.fileUrl, response?.fileName || '技术标投标文件.pdf')
      showToast?.(downloaded ? 'PDF 已生成并开始下载' : (response?.message || 'PDF 已生成'))
    } catch (e) {
      showToast?.(e?.message || 'PDF 生成失败', 'error')
    } finally {
      setPdfPreparing(false)
    }
  }

  const handleApplyTechnicalFormat = async (preset = formatPreset) => {
    if (formatApplying) return
    setFormatApplying(preset)
    try {
      const payload = preset === 'custom' ? { preset, styleOverrides: customFormat } : { preset }
      const response = await technicalDocumentAPI.technicalFormat(id, payload)
      setData(response?.payload?.document || response?.document || data)
      setFinalData(await technicalDocumentAPI.final(id).catch(() => finalData))
      setOnlyofficeError('')
      showToast?.(response?.message || '技术标格式已切换')
    } catch (e) {
      showToast?.(e?.message || '技术标格式切换失败', 'error')
    } finally {
      setFormatApplying('')
    }
  }

  const updateCustomFormat = (field, value) => {
    setCustomFormat((current) => ({ ...current, [field]: value }))
  }

  const updateCustomNumber = (field, value) => {
    const parsed = Number(value)
    setCustomFormat((current) => ({ ...current, [field]: Number.isFinite(parsed) ? parsed : '' }))
  }

  const renderFormatNumberInput = (field, label, props = {}) => (
    <label className="flex flex-col gap-1 text-xs font-semibold text-on-surface-variant">
      {label}
      <input
        type="number"
        value={customFormat[field]}
        onChange={(event) => updateCustomNumber(field, event.target.value)}
        className="h-9 rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
        {...props}
      />
    </label>
  )

  const renderFormatFontSelect = (field, label, options) => (
    <label className="flex flex-col gap-1 text-xs font-semibold text-on-surface-variant">
      {label}
      <select
        value={customFormat[field]}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  )

  const renderFormatTextInput = (field, label, props = {}) => (
    <label className="flex flex-col gap-1 text-xs font-semibold text-on-surface-variant">
      {label}
      <input
        type="text"
        value={customFormat[field]}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
        {...props}
      />
    </label>
  )

  const renderTechnicalFormatPanel = () => (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface-container-lowest shadow-[0_1px_2px_rgba(13,33,55,0.05)]">
      <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-surface-container-high px-4 py-3">
        <h3 className="truncate text-base font-semibold text-on-surface">技术标格式设置</h3>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-1 gap-2">
          {technicalFormatPresets.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => setFormatPreset(preset.key)}
              className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${formatPreset === preset.key ? 'border-primary bg-primary/10 text-primary' : 'border-surface-container-high bg-white text-on-surface hover:bg-surface-container-low'}`}
            >
              <span className="block text-sm font-semibold">{preset.label}</span>
              <span className="mt-0.5 block text-xs text-on-surface-variant">{preset.description}</span>
            </button>
          ))}
        </div>

        {formatPreset === 'custom' && (
          <div className="mt-4 space-y-4">
            <div>
              <div className="text-sm font-semibold text-on-surface">正文格式</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatFontSelect('bodyZhFont', '中文字体', FONT_OPTIONS.zh)}
                {renderFormatFontSelect('bodyEnFont', '英文字体', FONT_OPTIONS.en)}
                {renderFormatNumberInput('bodySizePt', '正文字号 pt', { min: 8, max: 22, step: 0.5 })}
                {renderFormatNumberInput('bodyLineSpacing', '正文行距', { min: 1, max: 3, step: 0.05 })}
                {renderFormatNumberInput('bodyFirstLineIndentChars', '首行缩进字符', { min: 0, max: 4, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">标题字号</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatNumberInput('heading1SizePt', '一级标题 pt', { min: 8, max: 26, step: 0.5 })}
                {renderFormatNumberInput('heading2SizePt', '二级标题 pt', { min: 8, max: 24, step: 0.5 })}
                {renderFormatNumberInput('heading3SizePt', '三级标题 pt', { min: 8, max: 22, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">页面与表格</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatNumberInput('pageTopCm', '上边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageBottomCm', '下边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageLeftCm', '左边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageRightCm', '右边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatFontSelect('tableZhFont', '表格字体', FONT_OPTIONS.zh)}
                {renderFormatNumberInput('tableSizePt', '表格字号 pt', { min: 8, max: 16, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">目录与页眉</div>
              <div className="mt-2 space-y-2">
                <label className="flex items-center gap-2 text-sm text-on-surface">
                  <input
                    type="checkbox"
                    checked={Boolean(customFormat.insertToc)}
                    onChange={(event) => updateCustomFormat('insertToc', event.target.checked)}
                  />
                  缺少目录时自动插入目录
                </label>
                <label className="flex items-center gap-2 text-sm text-on-surface">
                  <input
                    type="checkbox"
                    checked={Boolean(customFormat.tocPageBreakAfter)}
                    onChange={(event) => updateCustomFormat('tocPageBreakAfter', event.target.checked)}
                  />
                  目录后分页
                </label>
                {renderFormatTextInput('headerTextTemplate', '页眉模板', { placeholder: '{projectName}技术标投标文件' })}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-surface-container-high bg-surface-container-low p-3">
        <button
          type="button"
          onClick={() => handleApplyTechnicalFormat(formatPreset)}
          disabled={!!formatApplying}
          className="w-full rounded-md bg-secondary px-4 py-2 text-sm font-semibold text-on-secondary hover:bg-secondary/90 disabled:opacity-50"
        >
          {formatApplying ? '应用中...' : formatPreset === 'custom' ? '应用自定义格式' : '应用标准格式'}
        </button>
      </div>
    </section>
  )

  if (loading) {
    return (
      <PageLoading
        title="正在打开技术标共创文档..."
        description="正在加载技术标正文、OnlyOffice 会话和最终稿状态。"
      />
    )
  }

  if (error) {
    return (
      <PageError
        title="技术标共创文档加载失败"
        description={error}
        onRetry={loadDocument}
      />
    )
  }

  return (
    <div className="stage-page flex flex-col gap-4 animate-fade-in">
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />
      <StageBreadcrumb projectId={id} activeKey="editor" />

      <div className="grid min-h-[720px] grid-cols-1 items-stretch gap-4 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
        <section className="rounded-md border border-outline-variant/60 bg-white shadow-[0_1px_2px_rgba(13,33,55,0.05)]">
          <div className="flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high px-4 py-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-outline">技术标共创编辑</p>
              <h2 className="mt-1 text-lg font-headline font-bold text-on-surface">{projectName}</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-surface-container-low px-3 py-1 text-xs font-semibold text-on-surface-variant">
                {fileName}
              </span>
              <Button variant="secondary" size="sm" onClick={loadDocument}>刷新</Button>
              <Button variant="secondary" size="sm" onClick={handlePreparePdf} disabled={pdfPreparing}>
                {pdfPreparing ? '生成中...' : '导出 PDF'}
              </Button>
            </div>
          </div>

          <div className="min-h-[720px] p-4">
            {useFallbackEditor ? (
              <div className="flex min-h-[680px] flex-col gap-3">
                {onlyofficeError ? (
                  <div className="rounded-md border border-error/20 bg-error-container px-3 py-2 text-sm text-error">
                    {onlyofficeError}
                  </div>
                ) : null}
                <textarea
                  value={fallbackContent}
                  onChange={(event) => setFallbackContent(event.target.value)}
                  className="min-h-[620px] flex-1 rounded-md border border-surface-container-high bg-white p-4 font-mono text-sm leading-6 text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <div className="flex justify-end">
                  <Button variant="primary" onClick={handleSaveFallback} disabled={savingFallback}>
                    {savingFallback ? '保存中...' : '保存文本兜底'}
                  </Button>
                </div>
              </div>
            ) : (
              <OnlyOfficeEmbed
                session={data?.onlyoffice}
                className="h-full min-h-[680px] w-full rounded-md border border-outline-variant bg-white"
                onReady={() => setOnlyofficeError('')}
                onError={(message) => setOnlyofficeError(message || 'OnlyOffice 文档加载失败，已切换到文本兜底。')}
              />
            )}
          </div>
        </section>

        {renderTechnicalFormatPanel()}
      </div>
    </div>
  )
}
