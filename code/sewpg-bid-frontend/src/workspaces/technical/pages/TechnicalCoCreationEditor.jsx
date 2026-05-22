import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { documentAPI, projectsAPI, stagesAPI } from '../../../api'
import { PageError, PageLoading } from '../components/TechnicalPageState'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/TechnicalOnlyOfficeWorkspace'
import ProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import StageGroupNav from '../components/TechnicalStageGroupNav'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

const formatDateTime = (value) => {
  if (!value) return '未保存'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未保存'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const businessFormatPresets = [
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

export default function CoCreationEditor({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [fallbackContent, setFallbackContent] = useState('')
  const [project, setProject] = useState(null)
  const [finalData, setFinalData] = useState(null)
  const [savingFallback, setSavingFallback] = useState(false)
  const [forceSaving, setForceSaving] = useState(false)
  const [finishingStage, setFinishingStage] = useState(false)
  const [chatMessages, setChatMessages] = useState([
    {
      role: 'assistant',
      content: '可在这里输入需要润色的段落、修改目标或风险问题。我会基于商务标上下文给出建议，不会自动改写 Word。',
    },
  ])
  const chatHistoryRef = useRef(null)
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [rewriteOriginal, setRewriteOriginal] = useState('')
  const [rewriteInstruction, setRewriteInstruction] = useState('优化为正式、审慎、可履约的商务投标表达，不改变事实、金额、日期和承诺边界。')
  const [rewriteSuggestion, setRewriteSuggestion] = useState(null)
  const [rewriteLoading, setRewriteLoading] = useState(false)
  const [rewriteApplying, setRewriteApplying] = useState(false)
  const [controlledRewriteOpen, setControlledRewriteOpen] = useState(false)
  const [businessRightTab, setBusinessRightTab] = useState('chat')
  const [formatPreset, setFormatPreset] = useState('standard')
  const [customFormat, setCustomFormat] = useState({
    bodyZhFont: '等线',
    bodyEnFont: 'Times New Roman',
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
    tableZhFont: '宋体',
    tableSizePt: 10.5,
    tableLineSpacing: 1,
    insertToc: true,
    tocPageBreakAfter: true,
    headerTextTemplate: '{projectName}投标文件-商务部分',
  })
  const [formatApplying, setFormatApplying] = useState('')

  const loadDocument = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [payload, projectPayload, finalPayload] = await Promise.all([
        documentAPI.get(id),
        projectsAPI.get(id).catch(() => null),
        documentAPI.final(id).catch(() => null),
      ])
      setData(payload)
      setProject(projectPayload)
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

  const hasOnlyOfficeSession = Boolean(data?.onlyoffice?.fileUrl && data?.onlyoffice?.callbackUrl)
  const useFallbackEditor = !hasOnlyOfficeSession || Boolean(onlyofficeError)
  const editorModeLabel = useFallbackEditor ? '文本兜底' : 'OnlyOffice 在线编辑'
  const isBusinessBid = String(project?.bidType || '').includes('商务')
  const pageTitle = isBusinessBid ? '商务标 S4 共创导出' : 'S5 人机共创'
  const pageDescription = isBusinessBid
    ? '在线编辑商务标正文，并在同一界面下载最终版 Word。'
    : '在线编辑生成后的投标文件正文，确认后进入导出阶段。'

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await documentAPI.save(id, { content })
      setData(response?.payload || data)
      showToast?.('文档已保存并回写')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const handleForceSave = async () => {
    setForceSaving(true)
    try {
      const response = await documentAPI.forceSave(id)
      setData(response?.payload || data)
      showToast?.('已刷新真实文档状态')
    } catch (e) {
      showToast?.(e?.message || '刷新文档状态失败', 'error')
    } finally {
      setForceSaving(false)
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
      const response = await documentAPI.businessChat(id, {
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
      const response = await documentAPI.businessRewriteSuggest(id, {
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
      const response = await documentAPI.businessRewriteApply(id, {
        originalText: rewriteSuggestion.originalText || rewriteOriginal,
        replacementText: rewriteSuggestion.replacementText,
        operator: '当前用户',
      })
      setData(response?.payload?.document || response?.document || data)
      setFinalData(await documentAPI.final(id).catch(() => finalData))
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
      const response = await documentAPI.businessFormat(id, payload)
      setData(response?.payload?.document || response?.document || data)
      setFinalData(await documentAPI.final(id).catch(() => finalData))
      setOnlyofficeError('')
      showToast?.(response?.message || '商务标格式已切换')
    } catch (e) {
      showToast?.(e?.message || '商务标格式切换失败', 'error')
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

  const handleFinishCoCreation = async () => {
    setFinishingStage(true)
    try {
      await stagesAPI.update(id, 5, { status: 'completed' })
      if (isBusinessBid) {
        showToast?.('商务标共创导出已完成。')
        setFinalData(await documentAPI.final(id).catch(() => finalData))
      } else {
        showToast?.('S5 共创已完成，已进入 S6 导出')
        navigate(projectRoute(id, '/export', workspaceSlug))
      }
    } catch (e) {
      showToast?.(e?.message || '共创完成失败，请稍后重试', 'error')
    } finally {
      setFinishingStage(false)
    }
  }

  const renderDocumentEditor = (minHeight = '680px') => {
    const minHeightClass = minHeight === '690px' ? 'min-h-[690px]' : 'min-h-[680px]'
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
            <div className="mt-0.5 text-xs text-on-surface-variant">
              仅用于咨询、润色建议和风险提示，不会自动改写 Word；需要写入正文时请使用下方受控应用模块。
            </div>
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
              <p className="mt-1 text-xs leading-5 text-on-surface-variant">
                先从左侧 Word 复制原文段落，AI 只生成替换建议；点击确认后，后端只在唯一匹配的位置精确替换。
              </p>
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
                    <div className="rounded-md bg-warning/10 px-3 py-2 text-on-surface">
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
          <span className="text-xs text-on-surface-variant">真实调用后台 opencode；不会自动改写 Word。</span>
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
          {businessFormatPresets.map((preset) => (
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
                {renderFormatTextInput('bodyZhFont', '中文字体')}
                {renderFormatTextInput('bodyEnFont', '英文字体')}
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
                {renderFormatTextInput('tableZhFont', '表格字体')}
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
                {renderFormatTextInput('headerTextTemplate', '页眉模板', { placeholder: '{projectName}投标文件-商务部分' })}
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
        <div className="mt-3 space-y-1 text-xs text-on-surface-variant">
          <div>最近保存：{formatDateTime(data?.lastSavedAt)}</div>
          <div>当前文件：{data?.fileName || '-'}</div>
        </div>
      </div>
    </>
  )

  const renderBusinessWorkspace = () => (
    <div className="grid min-h-[780px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/50 bg-white shadow-[0_1px_3px_rgba(13,33,55,0.08)]">
        <div className="flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-on-surface">商务标正文预览</h3>
            <p className="mt-1 truncate text-xs text-outline" title={data?.fileName || ''}>{data?.fileName || '未生成文档'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
              {editorModeLabel}
            </span>
            <button
              onClick={handleForceSave}
              disabled={forceSaving}
              className="rounded-md bg-surface-container-high px-3 py-1.5 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
            >
              {forceSaving ? '刷新中...' : '刷新文档'}
            </button>
            <a
              href={finalData?.fileUrl || data?.fileUrl || '#'}
              download={finalData?.fileName || data?.fileName || '商务标投标文件.docx'}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container"
            >
              下载Word
            </a>
          </div>
        </div>
        <div className="min-h-0 flex-1 p-4">
          {onlyofficeError && (
            <div className="mb-3 rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
              {onlyofficeError}
            </div>
          )}
          {renderDocumentEditor('690px')}
        </div>
      </section>

      <aside className="flex h-[780px] min-h-0 flex-col overflow-hidden">
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/50 bg-surface-container-lowest shadow-[0_1px_3px_rgba(13,33,55,0.08)]">
          <div className="border-b border-surface-container-high bg-surface-container-low px-3 pt-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-on-surface">商务标共创工具</h3>
                <p className="mt-1 text-xs text-outline">
                  {businessRightTab === 'chat' ? '调用后台 opencode 进行对话与润色。' : '按标准版或自定义参数重新规范正文格式。'}
                </p>
              </div>
              <span className="rounded-full bg-surface-container-high px-2 py-1 text-[11px] font-semibold text-on-surface-variant">v{data?.version || 1}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[
                { key: 'chat', label: 'AI 对话' },
                { key: 'format', label: '格式设置' },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setBusinessRightTab(tab.key)}
                  className={`rounded-t-md px-3 py-2 text-sm font-semibold transition-colors ${businessRightTab === tab.key ? 'bg-surface-container-lowest text-primary shadow-[inset_0_-2px_0_var(--color-primary)]' : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim'}`}
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

  if (loading) return <PageLoading title={isBusinessBid ? '正在加载 S4 共创导出文档...' : '正在加载 S5 人机共创文档...'} />
  if (error) return <PageError title="文档加载失败" description={error} onRetry={loadDocument} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />
      <div className="rounded-lg border border-outline-variant/55 bg-surface-container-low px-5 py-4 shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
        <div className="flex flex-col gap-3.5 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-col gap-2.5 lg:flex-row lg:items-center">
            <StageGroupNav
              current="editor"
              variant="compact"
              items={[
                { key: 'editor', label: '共创编辑', icon: 'edit_document', path: '/editor' },
                { key: 'export', label: '最终导出', icon: 'download', path: '/export' },
              ]}
            />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-base font-headline font-bold leading-tight text-on-surface">{pageTitle}</h1>
                <span className={`inline-flex h-6 items-center rounded-md px-2 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
                  {editorModeLabel}
                </span>
              </div>
              <p className="mt-1 truncate text-xs leading-relaxed text-on-surface-variant" title={pageDescription}>
                {pageDescription}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2.5 xl:justify-end">
            <button
              onClick={loadDocument}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-surface-container-high px-3.5 text-xs font-semibold text-on-surface-variant transition-colors hover:bg-surface-dim"
            >
              <span className="material-symbols-outlined text-[16px] leading-none">refresh</span>
              刷新
            </button>
            <button
              onClick={handleFinishCoCreation}
              disabled={finishingStage}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-secondary px-3.5 text-xs font-semibold text-on-secondary transition-colors hover:bg-secondary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px] leading-none">arrow_forward</span>
              {finishingStage ? '处理中...' : isBusinessBid ? '完成共创导出' : '进入下一阶段'}
            </button>
          </div>
        </div>
        <div className="mt-3 grid gap-1.5 rounded-md bg-surface-container-lowest px-4 py-3 text-xs leading-relaxed text-on-surface-variant lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-4">
          <span className="whitespace-nowrap">当前文件：{data?.fileName || '未生成文档'}</span>
          <span className="truncate text-outline" title={data?.sourceFileName || '-'}>
            来源：{data?.sourceFileName || '-'}
          </span>
          <span className="whitespace-nowrap text-outline">最近保存：{formatDateTime(data?.lastSavedAt)}</span>
        </div>
      </div>

      {isBusinessBid ? renderBusinessWorkspace() : (

      <OnlyOfficeWorkspace
        heightClass="min-h-[720px]"
        gridClassName="xl:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]"
        documentTitle="共创文档"
        documentSubtitle={data?.fileName || '未生成文档'}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${useFallbackEditor ? 'bg-error-container text-on-error-container' : 'bg-secondary-container text-on-secondary-container'}`}>
            {editorModeLabel}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex min-h-[56px] flex-col justify-center border-b border-surface-container-high bg-surface-container-low px-4 py-2">
              <h3 className="text-base font-semibold text-on-surface">文档上下文</h3>
              <p className="mt-0.5 truncate text-xs text-outline" title={data?.sourceFileName || '-'}>
                来源：{data?.sourceFileName || '-'}
              </p>
            </div>
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-xs text-on-surface-variant">文件名</div>
                  <div className="mt-1 break-words font-medium text-on-surface">{data?.fileName || '-'}</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md bg-surface-container-low px-3 py-2">
                    <div className="text-xs text-on-surface-variant">版本</div>
                    <div className="mt-1 font-semibold text-on-surface">v{data?.version || 1}</div>
                  </div>
                  <div className="rounded-md bg-surface-container-low px-3 py-2">
                    <div className="text-xs text-on-surface-variant">模式</div>
                    <div className="mt-1 font-semibold text-on-surface">{editorModeLabel}</div>
                  </div>
                </div>
                <div>
                  <div className="text-xs text-on-surface-variant">最近保存</div>
                  <div className="mt-1 text-on-surface">{formatDateTime(data?.lastSavedAt)}</div>
                </div>
              </div>

              {onlyofficeError && (
                <div className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
                  {onlyofficeError}
                </div>
              )}

              <button
                onClick={handleForceSave}
                disabled={forceSaving}
                className="flex h-8 w-full items-center justify-center rounded-md bg-primary px-3 text-xs font-semibold text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
              >
                {forceSaving ? '刷新中...' : '刷新文档状态'}
              </button>

              {isBusinessBid && (
                <div className="rounded-md border border-surface-container-high bg-white p-3 text-sm">
                  <div className="font-semibold text-on-surface">最终版下载</div>
                  <div className="mt-2 space-y-1 text-xs text-on-surface-variant">
                    <div>文件：{finalData?.fileName || data?.fileName || '-'}</div>
                    <div>版本：v{finalData?.version || data?.version || 1}</div>
                    <div>最近保存：{formatDateTime(finalData?.lastSavedAt || data?.lastSavedAt)}</div>
                  </div>
                  <a
                    href={finalData?.fileUrl || data?.fileUrl || '#'}
                    download={finalData?.fileName || data?.fileName || '商务标投标文件.docx'}
                    onClick={() => showToast?.('开始下载商务标最终版 Word')}
                    className="mt-3 inline-flex h-8 w-full items-center justify-center rounded-md bg-primary px-3 text-xs font-semibold text-on-primary transition-colors hover:bg-primary-container"
                  >
                    下载最终版 Word
                  </a>
                </div>
              )}
            </div>
          </div>
        )}
      >
        <div className={useFallbackEditor ? 'hidden' : 'min-h-0 flex-1'}>
          <OnlyOfficeEmbed
            session={data?.onlyoffice}
            className="h-full min-h-[620px] w-full rounded-md border border-outline-variant bg-white"
            onReady={() => setOnlyofficeError('')}
            onError={(message) => setOnlyofficeError(message)}
          />
        </div>

        <div className={useFallbackEditor ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
          <textarea
            value={fallbackContent}
            onChange={(event) => setFallbackContent(event.target.value)}
            className="min-h-[600px] flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
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
      </OnlyOfficeWorkspace>
      )}
    </div>
  )
}
