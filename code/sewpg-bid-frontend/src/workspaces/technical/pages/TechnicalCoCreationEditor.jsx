import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { technicalDocumentAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'

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

const TECHNICAL_BID_LABEL = '技术标'
const TECHNICAL_DOCUMENT_PART_LABEL = '技术部分'

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
  const [finalData, setFinalData] = useState(null)
  const [fallbackContent, setFallbackContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [savingFallback, setSavingFallback] = useState(false)
  const [technicalPreviewFullscreen, setTechnicalPreviewFullscreen] = useState(false)
  const [pdfPreparing, setPdfPreparing] = useState(false)
  const [pdfData, setPdfData] = useState(null)
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
    headerTextTemplate: `{projectName}投标文件-${TECHNICAL_DOCUMENT_PART_LABEL}`,
  })

  const loadDocument = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, finalPayload] = await Promise.all([
        technicalDocumentAPI.get(id),
        technicalDocumentAPI.final(id).catch(() => null),
      ])
      setData(payload)
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
  const fileName = finalData?.fileName || data?.fileName || '技术标投标文件.docx'
  const bidLabel = TECHNICAL_BID_LABEL
  const defaultWordFileName = `${TECHNICAL_BID_LABEL}投标文件.docx`
  const defaultPdfFileName = `${TECHNICAL_BID_LABEL}投标文件.pdf`
  const editorModeLabel = useFallbackEditor ? '文本兜底' : 'OnlyOffice 在线编辑'

  useEffect(() => {
    if (!technicalPreviewFullscreen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setTechnicalPreviewFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [technicalPreviewFullscreen])

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
      setPdfData(response)
      const downloaded = triggerDownload(response?.fileUrl, response?.fileName || defaultPdfFileName)
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
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-on-surface-variant">{label}</span>
      <input
        type="number"
        value={customFormat[field]}
        min={props.min}
        max={props.max}
        step={props.step || 0.1}
        onChange={(event) => updateCustomNumber(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </label>
  )

  const renderFormatFontSelect = (field, label, options) => (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-on-surface-variant">{label}</span>
      <select
        value={customFormat[field] || options[0] || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  )

  const renderFormatTextInput = (field, label, props = {}) => (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-on-surface-variant">{label}</span>
      <input
        type="text"
        value={customFormat[field] || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
        {...props}
      />
    </label>
  )

  const renderDocumentEditor = (minHeight = '740px') => {
    const minHeightClass = minHeight === '740px' ? 'min-h-[740px]' : minHeight === '690px' ? 'min-h-[690px]' : 'min-h-[680px]'
    return (
      <>
        <div className={useFallbackEditor ? 'hidden' : 'min-h-0 flex-1'}>
          <OnlyOfficeEmbed
            session={data?.onlyoffice}
            className={`h-full ${minHeightClass} w-full rounded-md border border-outline-variant bg-white`}
            onReady={() => setOnlyofficeError('')}
            onError={(message) => setOnlyofficeError(message || 'OnlyOffice 文档加载失败，已切换到文本兜底。')}
          />
        </div>

        <div className={useFallbackEditor ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
          <textarea
            value={fallbackContent}
            onChange={(event) => setFallbackContent(event.target.value)}
            className={`${minHeightClass} flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30`}
          />
          <div className="flex justify-end">
            <Button variant="primary" onClick={handleSaveFallback} disabled={savingFallback}>
              {savingFallback ? '保存中...' : '保存回写'}
            </Button>
          </div>
        </div>
      </>
    )
  }

  const renderTechnicalFormatPanel = () => (
    <section className="business-panel flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface-container-lowest shadow-[0_1px_2px_rgba(13,33,55,0.05)]">
      <div className="business-section-head business-editor-tool-head flex min-h-[58px] items-center justify-between gap-3 border-b border-surface-container-high px-4 py-3">
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
          <div className="mt-4 space-y-4 rounded-md border border-surface-container-high bg-white p-3">
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
                {renderFormatTextInput('headerTextTemplate', '页眉模板', { placeholder: `{projectName}投标文件-${TECHNICAL_DOCUMENT_PART_LABEL}` })}
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

  const renderProjectWorkspace = () => (
    <div className="business-ui-shell grid min-h-[885px] grid-cols-1 items-stretch gap-4 xl:min-h-[calc(100vh-4.5rem)] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className={`business-panel flex min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-white shadow-[0_1px_2px_rgba(13,33,55,0.05)] ${
        technicalPreviewFullscreen ? 'fixed inset-0 z-[160] rounded-none border-0' : ''
      }`}>
        <div className="business-section-head flex min-h-[58px] flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-on-surface">{bidLabel}正文预览</h3>
            <p className="mt-1 truncate text-xs text-outline" title={fileName}>{fileName || '未生成文档'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
              {editorModeLabel}
            </span>
            <IconButton
              type="button"
              aria-label={technicalPreviewFullscreen ? '退出全屏' : '全屏查看'}
              title={technicalPreviewFullscreen ? '退出全屏' : '全屏查看'}
              icon={technicalPreviewFullscreen ? 'close_fullscreen' : 'open_in_full'}
              onClick={() => setTechnicalPreviewFullscreen((value) => !value)}
              size="sm"
              variant="quiet"
            />
            <Button
              as="a"
              href={finalData?.fileUrl || data?.fileUrl || '#'}
              download={finalData?.fileName || data?.fileName || defaultWordFileName}
              size="sm"
              variant="primary"
            >
              下载Word
            </Button>
            {pdfData?.fileUrl ? (
              <Button
                type="button"
                onClick={() => triggerDownload(pdfData.fileUrl, pdfData.fileName || defaultPdfFileName)}
                size="sm"
                variant="primary"
              >
                下载PDF
              </Button>
            ) : (
              <Button
                type="button"
                onClick={handlePreparePdf}
                disabled={pdfPreparing}
                size="sm"
                variant="primary"
              >
                {pdfPreparing ? '生成中...' : '下载PDF'}
              </Button>
            )}
          </div>
        </div>
        <div className="min-h-0 flex-1 p-4">
          {onlyofficeError && (
            <div className="mb-3 rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
              {onlyofficeError}
            </div>
          )}
          {renderDocumentEditor('740px')}
        </div>
      </section>

      <aside className="flex min-h-[885px] flex-col overflow-hidden xl:h-[calc(100vh-4.5rem)]">
        {renderTechnicalFormatPanel()}
      </aside>
    </div>
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
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />
      {renderProjectWorkspace()}
    </div>
  )
}
