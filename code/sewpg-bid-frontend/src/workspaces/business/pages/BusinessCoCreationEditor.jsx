import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { businessDocumentAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import BusinessProjectStageProgress from '../components/BusinessProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import { OPEN_SOURCE_FONT_OPTIONS } from '../../shared/fontOptions'

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

const documentFormatPresets = [
  {
    key: 'standard',
    label: '标准版',
    description: '统一标题、正文、表格、目录、页眉和分页。',
  },
  {
    key: 'custom',
    label: '自定义格式',
    description: '按用户设置的字体、字号、行距、页边距、目录和页眉执行清洗。',
  },
]

const BUSINESS_BID_LABEL = '商务标'
const BUSINESS_DOCUMENT_PART_LABEL = '商务部分'

export default function BusinessCoCreationEditor({ showToast }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [fallbackContent, setFallbackContent] = useState('')
  const [finalData, setFinalData] = useState(null)
  const [savingFallback, setSavingFallback] = useState(false)
  const [businessPreviewFullscreen, setBusinessPreviewFullscreen] = useState(false)
  const [pdfPreparing, setPdfPreparing] = useState(false)
  const [pdfData, setPdfData] = useState(null)
  const bidLabel = BUSINESS_BID_LABEL
  const documentPartLabel = BUSINESS_DOCUMENT_PART_LABEL
  const defaultWordFileName = `${BUSINESS_BID_LABEL}投标文件.docx`
  const defaultPdfFileName = `${BUSINESS_BID_LABEL}投标文件.pdf`
  const [chatMessages, setChatMessages] = useState(() => [
    {
      role: 'assistant',
      content: '可在这里输入需要润色的段落、修改目标或风险问题。我会基于当前标书上下文给出建议，不会自动改写 Word。',
    },
  ])
  const chatHistoryRef = useRef(null)
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [rewriteOriginal, setRewriteOriginal] = useState('')
  const [rewriteInstruction, setRewriteInstruction] = useState('优化为正式、审慎、可履约的投标表达，不改变事实、金额、日期和承诺边界。')
  const [rewriteSuggestion, setRewriteSuggestion] = useState(null)
  const [rewriteLoading, setRewriteLoading] = useState(false)
  const [rewriteApplying, setRewriteApplying] = useState(false)
  const [controlledRewriteOpen, setControlledRewriteOpen] = useState(false)
  const [businessRightTab, setBusinessRightTab] = useState('chat')
  const [formatPreset, setFormatPreset] = useState('standard')
  const [customFormat, setCustomFormat] = useState({
    bodyZhFont: 'Noto Sans CJK SC',
    bodyEnFont: 'Liberation Serif',
    bodySizePt: 12,
    bodyLineSpacing: 1.5,
    bodyFirstLineIndentChars: 2,
    heading1SizePt: 15,
    heading2SizePt: 14,
    heading3SizePt: 12,
    heading4SizePt: 12,
    pageTopCm: 2.54,
    pageBottomCm: 2.54,
    pageLeftCm: 3.18,
    pageRightCm: 3.18,
    tableZhFont: 'Noto Serif CJK SC',
    tableSizePt: 10.5,
    tableLineSpacing: 1,
    insertToc: true,
    tocPageBreakAfter: true,
    headerTextTemplate: `{projectName}投标文件-${BUSINESS_DOCUMENT_PART_LABEL}`,
  })
  const [formatApplying, setFormatApplying] = useState('')

  const loadDocument = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, finalPayload] = await Promise.all([
        businessDocumentAPI.get(id),
        businessDocumentAPI.final(id).catch(() => null),
      ])
      setData(payload)
      setFinalData(finalPayload)
      setFallbackContent(payload?.fallback?.content || '')
      setOnlyofficeError('')
    } catch (e) {
      setError(e?.message || '共创导出文档加载失败')
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

  useEffect(() => {
    if (!chatHistoryRef.current) return
    chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight
  }, [chatMessages, chatLoading])

  useEffect(() => {
    if (!businessPreviewFullscreen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setBusinessPreviewFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [businessPreviewFullscreen])

  const hasOnlyOfficeSession = Boolean(data?.onlyoffice?.fileUrl && data?.onlyoffice?.callbackUrl)
  const useFallbackEditor = !hasOnlyOfficeSession || Boolean(onlyofficeError)
  const editorModeLabel = useFallbackEditor ? '文本兜底' : 'OnlyOffice 在线编辑'

  useEffect(() => {
    setChatMessages((current) => {
      if (current.length !== 1 || current[0]?.role !== 'assistant') return current
      return [{
        ...current[0],
        content: `可在这里输入需要润色的段落、修改目标或风险问题。我会基于${bidLabel}上下文给出建议，不会自动改写 Word。`,
      }]
    })
    setRewriteInstruction((current) => (
      current.includes('商务投标表达') || current === '优化为正式、审慎、可履约的投标表达，不改变事实、金额、日期和承诺边界。'
        ? `优化为正式、审慎、可履约的${bidLabel}投标表达，不改变事实、金额、日期和承诺边界。`
        : current
    ))
    setCustomFormat((current) => {
      const currentHeader = String(current.headerTextTemplate || '')
      if (currentHeader && !currentHeader.includes('当前部分') && !currentHeader.includes(BUSINESS_DOCUMENT_PART_LABEL)) return current
      return { ...current, headerTextTemplate: `{projectName}投标文件-${documentPartLabel}` }
    })
  }, [bidLabel, documentPartLabel])

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await businessDocumentAPI.save(id, { content })
      setData(response?.payload || data)
      showToast?.('文档已保存并回写')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const handleBusinessChat = async () => {
    const message = chatInput.trim()
    if (!message || chatLoading) return
    const nextMessages = [...chatMessages, { role: 'user', content: message }]
    setChatMessages(nextMessages)
    setChatInput('')
    setChatLoading(true)
    try {
      const response = await businessDocumentAPI.businessChat(id, {
        message,
        history: nextMessages,
      })
      setChatMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response?.reply || '未返回有效建议。',
          fallbackModelUsed: Boolean(response?.fallbackModelUsed),
          modelLabel: response?.providerId && response?.modelId ? `${response.providerId}/${response.modelId}` : '',
        },
      ])
      if (response?.fallbackModelUsed) showToast?.('系统设置模型不可用，已使用 opencode 默认模型重试成功。', 'warning')
    } catch (e) {
      setChatMessages((current) => [
        ...current,
        { role: 'assistant', content: e?.message || 'AI 对话失败，请稍后重试。', error: true },
      ])
      showToast?.(e?.message || 'AI 对话失败', 'error')
    } finally {
      setChatLoading(false)
    }
  }

  const handleSuggestRewrite = async () => {
    const originalText = rewriteOriginal.trim()
    const instruction = rewriteInstruction.trim()
    if (!originalText) {
      showToast?.('请先粘贴需要润色并应用到正文的原文段落。', 'error')
      return
    }
    setRewriteLoading(true)
    setRewriteSuggestion(null)
    try {
      const response = await businessDocumentAPI.businessRewriteSuggest(id, {
        originalText,
        instruction,
      })
      setRewriteSuggestion(response?.suggestion || null)
      if (response?.fallbackModelUsed) showToast?.('系统设置模型不可用，已使用 opencode 默认模型生成润色建议。', 'warning')
      else showToast?.(response?.message || '已生成润色建议')
    } catch (e) {
      showToast?.(e?.message || '生成润色建议失败', 'error')
    } finally {
      setRewriteLoading(false)
    }
  }

  const handleApplyRewrite = async () => {
    if (!rewriteSuggestion?.replacementText || rewriteApplying) return
    setRewriteApplying(true)
    try {
      const response = await businessDocumentAPI.businessRewriteApply(id, {
        originalText: rewriteSuggestion.originalText || rewriteOriginal,
        replacementText: rewriteSuggestion.replacementText,
        operator: '当前用户',
      })
      setData(response?.payload?.document || response?.document || data)
      setFinalData(await businessDocumentAPI.final(id).catch(() => finalData))
      setOnlyofficeError('')
      setRewriteOriginal('')
      setRewriteSuggestion(null)
      showToast?.(response?.message || '已应用到 Word 正文')
    } catch (e) {
      showToast?.(e?.message || '应用到 Word 失败', 'error')
    } finally {
      setRewriteApplying(false)
    }
  }

  const handleApplyBusinessFormat = async (preset = formatPreset) => {
    if (formatApplying) return
    setFormatApplying(preset)
    try {
      const payload = preset === 'custom' ? { preset, styleOverrides: customFormat } : { preset }
      const response = await businessDocumentAPI.businessFormat(id, payload)
      setData(response?.payload?.document || response?.document || data)
      setFinalData(await businessDocumentAPI.final(id).catch(() => finalData))
      setOnlyofficeError('')
      showToast?.(response?.message || `${bidLabel}格式已切换`)
    } catch (e) {
      showToast?.(e?.message || `${bidLabel}格式切换失败`, 'error')
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

  const handlePreparePdf = async () => {
    if (pdfPreparing) return
    setPdfPreparing(true)
    try {
      const response = await businessDocumentAPI.finalPdf(id)
      setPdfData(response)
      const downloaded = triggerDownload(response?.fileUrl, response?.fileName || defaultPdfFileName)
      showToast?.(downloaded ? 'PDF 已生成并开始下载' : (response?.message || 'PDF 已生成'))
    } catch (e) {
      showToast?.(e?.message || 'PDF 生成失败', 'error')
    } finally {
      setPdfPreparing(false)
    }
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

  const renderFormatTextInput = (field, label, props = {}) => (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-on-surface-variant">{label}</span>
      <input
        type="text"
        value={customFormat[field] || ''}
        placeholder={props.placeholder || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </label>
  )

  const renderFormatFontSelect = (field, label, options = OPEN_SOURCE_FONT_OPTIONS.zh) => (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-on-surface-variant">{label}</span>
      <select
        value={customFormat[field] || options[0]?.value || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      >
        {options.map((font) => (
          <option key={font.value} value={font.value}>{font.label}</option>
        ))}
      </select>
    </label>
  )

  const renderDocumentEditor = (minHeight = '680px') => {
    const minHeightClass = minHeight === '740px' ? 'min-h-[740px]' : minHeight === '690px' ? 'min-h-[690px]' : 'min-h-[680px]'
    return (
      <>
        <div className={useFallbackEditor ? 'hidden' : 'min-h-0 flex-1'}>
          <OnlyOfficeEmbed
            session={data?.onlyoffice}
            className={`h-full ${minHeightClass} w-full rounded-md border border-outline-variant bg-white`}
            onReady={() => setOnlyofficeError('')}
            onError={(message) => setOnlyofficeError(message)}
          />
        </div>

        <div className={useFallbackEditor ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
          <textarea
            value={fallbackContent}
            onChange={(event) => setFallbackContent(event.target.value)}
            className={`${minHeightClass} flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30`}
          />
          <div className="flex justify-end">
            <button
              onClick={handleSaveFallback}
              disabled={savingFallback}
              className="flex h-8 items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
            >
              {savingFallback ? '保存中...' : '保存回写'}
            </button>
          </div>
        </div>
      </>
    )
  }

  const renderBusinessChatPanel = () => (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-4">
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-surface-container-high bg-white">
          <div className="shrink-0 border-b border-surface-container-high px-3 py-2">
            <div className="text-sm font-semibold text-on-surface">通用 AI 对话</div>
          </div>
          <div ref={chatHistoryRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 pr-2">
            {chatMessages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`rounded-lg px-3 py-2 text-sm leading-6 ${message.role === 'user' ? 'ml-8 bg-primary text-on-primary' : message.error ? 'mr-8 bg-error/10 text-error' : 'mr-8 bg-surface-container-low text-on-surface'}`}
              >
                <div className="mb-1 text-[11px] font-semibold opacity-70">
                  {message.role === 'user' ? '我' : message.fallbackModelUsed ? `AI助手（${message.modelLabel || '默认模型'}）` : 'AI助手'}
                </div>
                <div className="whitespace-pre-wrap">{message.content}</div>
              </div>
            ))}
            {chatLoading && (
              <div className="mr-8 rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">AI 正在生成建议...</div>
            )}
          </div>
        </section>

        <section className="shrink-0 overflow-hidden rounded-lg border border-primary/20 bg-primary/5">
          <button
            type="button"
            onClick={() => setControlledRewriteOpen((value) => !value)}
            className="flex w-full items-start justify-between gap-3 px-3 py-3 text-left hover:bg-primary/10"
          >
            <div>
              <h4 className="text-sm font-semibold text-on-surface">受控应用到 Word</h4>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-primary">人工确认后写入</span>
              <span className="rounded-full bg-surface-container-high px-2 py-1 text-[11px] font-semibold text-on-surface-variant">
                {controlledRewriteOpen ? '收起' : '展开'}
              </span>
            </div>
          </button>

          {controlledRewriteOpen && (
            <div className="max-h-[420px] overflow-y-auto border-t border-primary/10 p-3">
              <div className="space-y-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-on-surface">原文段落</span>
                  <textarea
                    value={rewriteOriginal}
                    onChange={(event) => {
                      setRewriteOriginal(event.target.value)
                      setRewriteSuggestion(null)
                    }}
                    placeholder="从左侧 Word 预览中复制需要润色并替换的完整段落。为避免误替换，建议一次只处理一个段落。"
                    className="min-h-[96px] w-full resize-y rounded-md border border-surface-container-high bg-white px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-on-surface">润色要求</span>
                  <textarea
                    value={rewriteInstruction}
                    onChange={(event) => {
                      setRewriteInstruction(event.target.value)
                      setRewriteSuggestion(null)
                    }}
                    className="min-h-[72px] w-full resize-y rounded-md border border-surface-container-high bg-white px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </label>
                <button
                  type="button"
                  onClick={handleSuggestRewrite}
                  disabled={rewriteLoading || !rewriteOriginal.trim()}
                  className="w-full rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                >
                  {rewriteLoading ? '生成中...' : '生成润色建议'}
                </button>
              </div>

              {rewriteSuggestion && (
                <div className="mt-4 space-y-3 rounded-md border border-surface-container-high bg-white p-3">
                  <div>
                    <div className="text-xs font-semibold text-on-surface-variant">原文</div>
                    <div className="mt-1 max-h-28 overflow-auto rounded-md bg-surface-container-low px-3 py-2 text-xs leading-5 text-on-surface whitespace-pre-wrap">
                      {rewriteSuggestion.originalText || rewriteOriginal}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-on-surface-variant">建议替换文本</div>
                    <div className="mt-1 max-h-40 overflow-auto rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-sm leading-6 text-on-surface whitespace-pre-wrap">
                      {rewriteSuggestion.replacementText}
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-2 text-xs leading-5 text-on-surface-variant">
                    <div className="rounded-md bg-surface-container-low px-3 py-2">
                      <span className="font-semibold text-on-surface">修改理由：</span>{rewriteSuggestion.reason || '未返回修改理由'}
                    </div>
                    <div className="rounded-md border border-tertiary/30 bg-tertiary-container/60 px-3 py-2 text-on-tertiary-container">
                      <span className="font-semibold">风险提示：</span>{rewriteSuggestion.riskTip || '请人工复核事实、金额、日期和承诺边界。'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handleApplyRewrite}
                    disabled={rewriteApplying || !rewriteSuggestion.replacementText}
                    className="w-full rounded-md bg-secondary px-4 py-2 text-sm font-semibold text-on-secondary hover:bg-secondary/90 disabled:opacity-50"
                  >
                    {rewriteApplying ? '应用中...' : '确认应用到 Word'}
                  </button>
                  <p className="text-[11px] leading-5 text-on-surface-variant">
                    如果原文在 Word 中找不到，或匹配到多处，系统会拒绝替换并提示重新选择更精确的原文。
                  </p>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
      <div className="border-t border-surface-container-high bg-surface-container-low p-3">
        <textarea
          value={chatInput}
          onChange={(event) => setChatInput(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') handleBusinessChat()
          }}
          placeholder="输入要润色的段落、修改要求或风险问题。Ctrl/⌘ + Enter 发送。"
          className="min-h-[96px] w-full resize-none rounded-md border border-surface-container-high bg-white px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span />
          <button
            type="button"
            onClick={handleBusinessChat}
            disabled={chatLoading || !chatInput.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
          >
            {chatLoading ? '发送中...' : '发送给AI'}
          </button>
        </div>
      </div>
    </>
  )

  const renderBusinessFormatPanel = () => (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-1 gap-2">
          {documentFormatPresets.map((preset) => (
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
                {renderFormatFontSelect('bodyZhFont', '中文字体', OPEN_SOURCE_FONT_OPTIONS.zh)}
                {renderFormatFontSelect('bodyEnFont', '英文字体', OPEN_SOURCE_FONT_OPTIONS.en)}
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
                {renderFormatNumberInput('heading4SizePt', '四级标题 pt', { min: 8, max: 20, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">页面与表格</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatNumberInput('pageTopCm', '上边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageBottomCm', '下边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageLeftCm', '左边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageRightCm', '右边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatFontSelect('tableZhFont', '表格字体', OPEN_SOURCE_FONT_OPTIONS.zh)}
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
                {renderFormatTextInput('headerTextTemplate', '页眉模板', { placeholder: `{projectName}投标文件-${documentPartLabel}` })}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-surface-container-high bg-surface-container-low p-3">
        <button
          type="button"
          onClick={() => handleApplyBusinessFormat(formatPreset)}
          disabled={!!formatApplying}
          className="w-full rounded-md bg-secondary px-4 py-2 text-sm font-semibold text-on-secondary hover:bg-secondary/90 disabled:opacity-50"
        >
          {formatApplying ? '应用中...' : formatPreset === 'custom' ? '应用自定义格式' : '应用标准格式'}
        </button>
      </div>
    </>
  )

  const renderProjectWorkspace = () => (
    <div className="business-ui-shell grid min-h-[885px] grid-cols-1 items-stretch gap-4 xl:min-h-[calc(100vh-4.5rem)] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className={`business-panel flex min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-white shadow-[0_1px_2px_rgba(13,33,55,0.05)] ${
        businessPreviewFullscreen ? 'fixed inset-0 z-[160] rounded-none border-0' : ''
      }`}>
        <div className="business-section-head flex min-h-[58px] flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-on-surface">{bidLabel}正文预览</h3>
            <p className="mt-1 truncate text-xs text-outline" title={data?.fileName || ''}>{data?.fileName || '未生成文档'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
              {editorModeLabel}
            </span>
            <IconButton
              type="button"
              aria-label={businessPreviewFullscreen ? '退出全屏' : '全屏查看'}
              title={businessPreviewFullscreen ? '退出全屏' : '全屏查看'}
              icon={businessPreviewFullscreen ? 'close_fullscreen' : 'open_in_full'}
              onClick={() => setBusinessPreviewFullscreen((value) => !value)}
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
        <section className="business-panel flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface-container-lowest shadow-[0_1px_2px_rgba(13,33,55,0.05)]">
          <div className="business-section-head business-editor-tool-head flex items-center justify-between gap-3 border-b border-surface-container-high px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-base font-semibold text-on-surface">{bidLabel}共创工具</h3>
            </div>
            <div className="grid w-[176px] shrink-0 grid-cols-2 gap-1 rounded-md bg-surface-container-high p-1">
              {[
                { key: 'chat', label: 'AI 对话' },
                { key: 'format', label: '格式设置' },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setBusinessRightTab(tab.key)}
                  className={`rounded px-2 py-1.5 text-xs font-semibold transition-colors ${businessRightTab === tab.key ? 'bg-surface-container-lowest text-primary shadow-sm' : 'text-on-surface-variant hover:bg-surface-dim'}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          {businessRightTab === 'chat' ? renderBusinessChatPanel() : renderBusinessFormatPanel()}
        </section>
      </aside>
    </div>
  )

  if (loading) return <PageLoading title="正在加载共创导出文档..." />
  if (error) return <PageError title="文档加载失败" description={error} onRetry={loadDocument} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <BusinessProjectStageProgress projectId={id} showToast={showToast} />
      {renderProjectWorkspace()}
    </div>
  )
}
