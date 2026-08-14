import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { settingsAPI } from '../api'
import PageHeader from '../components/shared/PageHeader'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'
import Button from '../components/ui/Button'
import { allowedTemplateTypesFor } from '../utils/permissions'

const providerResponseMessage = (value) => {
  const text = String(value || '').trim()
  if (!text) return ''
  try {
    const parsed = JSON.parse(text)
    return String(parsed?.message || parsed?.error?.message || parsed?.detail || text)
  } catch {
    return text
  }
}

const safeMessage = (error, fallback) => {
  const base = error?.payload?.detail || error?.message || fallback
  const providerMessage = providerResponseMessage(error?.payload?.responseText)
  return providerMessage ? `${base}；Provider 返回：${providerMessage}` : base
}

const deepEqualByKeys = (left, right, keys) =>
  keys.every((key) => JSON.stringify(left?.[key]) === JSON.stringify(right?.[key]))

const todayVersionLabel = () => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}.${month}.${day}`
}

export default function Settings({ showToast = () => {}, currentUser = null }) {
  const [activeSection, setActiveSection] = useState('defaultTemplates')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [users, setUsers] = useState([])
  const [gateway, setGateway] = useState(null)
  const [gatewayDraft, setGatewayDraft] = useState({
    enabled: true,
    providerId: '',
    baseUrl: '',
    model: '',
    modelOptions: [],
    opencodeBaseUrl: '',
    timeoutMs: 30000,
    maxTokens: 4096,
    apiKey: '',
    apiKeyMasked: '',
  })
  const [gatewaySaving, setGatewaySaving] = useState(false)
  const [gatewayTesting, setGatewayTesting] = useState(false)
  const [gatewayTestResult, setGatewayTestResult] = useState(null)

  const [ocr, setOcr] = useState(null)
  const [ocrDraft, setOcrDraft] = useState({
    enabled: false,
    baseUrl: '',
    model: 'deepseek-ai/DeepSeek-OCR',
    timeoutMs: 60000,
    maxTokens: 2048,
    apiKey: '',
    apiKeyMasked: '',
  })
  const [ocrSaving, setOcrSaving] = useState(false)
  const [ocrTesting, setOcrTesting] = useState(false)
  const [ocrTestResult, setOcrTestResult] = useState(null)

  const [defaultTemplates, setDefaultTemplates] = useState([])
  const [defaultTemplateTypes, setDefaultTemplateTypes] = useState([])
  const [defaultTemplateUploadType, setDefaultTemplateUploadType] = useState('technical')
  const [defaultTemplateUploadVersion, setDefaultTemplateUploadVersion] = useState(todayVersionLabel)
  const [defaultTemplateUploading, setDefaultTemplateUploading] = useState(false)
  const [defaultTemplateActivatingId, setDefaultTemplateActivatingId] = useState('')
  const [defaultTemplateDeletingId, setDefaultTemplateDeletingId] = useState('')

  const [health, setHealth] = useState([])

  const defaultTemplateFileInputRef = useRef(null)

  const loadAll = useCallback(async (options = {}) => {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError('')

    try {
      const [usersRes, gatewayRes, ocrRes, defaultTemplatesRes, healthRes] = await Promise.all([
        settingsAPI.users.list(),
        settingsAPI.gateway.get(),
        settingsAPI.ocr.get(),
        settingsAPI.defaultTemplates.list(),
        settingsAPI.health(),
      ])
      setUsers(usersRes?.items || [])
      setGateway(gatewayRes || null)
      setGatewayDraft({
        enabled: Boolean(gatewayRes?.enabled),
        providerId: String(gatewayRes?.providerId || ''),
        baseUrl: String(gatewayRes?.baseUrl || gatewayRes?.endpoint || ''),
        model: String(gatewayRes?.model || ''),
        modelOptions: Array.isArray(gatewayRes?.modelOptions) ? gatewayRes.modelOptions : [],
        opencodeBaseUrl: String(gatewayRes?.opencodeBaseUrl || ''),
        timeoutMs: Number(gatewayRes?.timeoutMs || 30000),
        maxTokens: Number(gatewayRes?.maxTokens || 4096),
        apiKey: '',
        apiKeyMasked: String(gatewayRes?.apiKeyMasked || ''),
      })
      setOcr(ocrRes || null)
      setOcrDraft({
        enabled: Boolean(ocrRes?.enabled),
        baseUrl: String(ocrRes?.baseUrl || ''),
        model: String(ocrRes?.model || 'deepseek-ai/DeepSeek-OCR'),
        timeoutMs: Number(ocrRes?.timeoutMs || 60000),
        maxTokens: Number(ocrRes?.maxTokens || 2048),
        apiKey: '',
        apiKeyMasked: String(ocrRes?.apiKeyMasked || ''),
      })

      setDefaultTemplates(defaultTemplatesRes?.items || [])
      const templateTypeOptions = defaultTemplatesRes?.templateTypes || []
      setDefaultTemplateTypes(templateTypeOptions)
      setDefaultTemplateUploadType((prev) => {
        if (prev && templateTypeOptions.some((item) => item.key === prev)) return prev
        return templateTypeOptions[0]?.key || 'technical'
      })
      setHealth(Array.isArray(healthRes) ? healthRes : [])
    } catch (e) {
      console.error(e)
      const message = safeMessage(e, '设置中心加载失败，请稍后重试。')
      setError(message)
      if (options.silent) showToast(message, 'error')
    } finally {
      if (options.silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadAll()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadAll])

  const sections = [
    { id: 'defaultTemplates', icon: 'description', label: '默认 Word 模板', group: '系统核心' },
    { id: 'gateway', icon: 'hub', label: 'LLM 模型', group: '系统核心' },
    { id: 'ocr', icon: 'document_scanner', label: 'PDF/图片识别', group: '系统核心' },
    { id: 'users', icon: 'group', label: '用户', group: '系统核心' },
    { id: 'health', icon: 'monitor_heart', label: '健康', group: '系统核心' },
  ]

  const gatewayDirty = useMemo(() => {
    if (!gateway) return false
    return !deepEqualByKeys(gatewayDraft, gateway, ['enabled', 'providerId', 'baseUrl', 'model', 'opencodeBaseUrl', 'timeoutMs', 'maxTokens'])
      || Boolean(gatewayDraft.apiKey.trim())
  }, [gateway, gatewayDraft])

  const ocrDirty = useMemo(() => {
    if (!ocr) return false
    return !deepEqualByKeys(ocrDraft, ocr, ['enabled', 'baseUrl', 'model', 'timeoutMs', 'maxTokens'])
      || Boolean(ocrDraft.apiKey.trim())
  }, [ocr, ocrDraft])

  // 默认模板按角色隔离：T 技术标 / B 商务标 / TB 全部；无角色信息不过滤
  const allowedTemplateTypes = useMemo(() => allowedTemplateTypesFor(currentUser), [currentUser])
  const visibleTemplateTypes = useMemo(
    () => (allowedTemplateTypes ? defaultTemplateTypes.filter((item) => allowedTemplateTypes.includes(item.key)) : defaultTemplateTypes),
    [allowedTemplateTypes, defaultTemplateTypes],
  )
  const visibleDefaultTemplates = useMemo(
    () => (allowedTemplateTypes ? defaultTemplates.filter((item) => allowedTemplateTypes.includes(item.templateType)) : defaultTemplates),
    [allowedTemplateTypes, defaultTemplates],
  )
  const effectiveUploadType = visibleTemplateTypes.some((item) => item.key === defaultTemplateUploadType)
    ? defaultTemplateUploadType
    : visibleTemplateTypes[0]?.key || defaultTemplateUploadType

  const handleSaveGateway = async () => {
    if (!gatewayDirty) return
    setGatewaySaving(true)
    try {
      const result = await settingsAPI.gateway.update({
        enabled: gatewayDraft.enabled,
        providerId: gatewayDraft.providerId.trim(),
        baseUrl: gatewayDraft.baseUrl.trim(),
        model: gatewayDraft.model.trim(),
        modelId: gatewayDraft.model.trim(),
        opencodeBaseUrl: gatewayDraft.opencodeBaseUrl.trim(),
        timeoutMs: Number(gatewayDraft.timeoutMs || 0),
        maxTokens: Number(gatewayDraft.maxTokens || 0),
        ...(gatewayDraft.apiKey.trim() ? { apiKey: gatewayDraft.apiKey.trim() } : {}),
      })
      setGateway(result.config)
      setGatewayTestResult(result.opencodeRestartRequired ? {
        success: true,
        message: result.opencodeRuntimeConfigPath
          ? `配置已保存，并已生成 opencode 运行配置。请重启 opencode 容器后再生成目录；健康检查会在 opencode 实际生效配置与保存配置不一致时给出 warning。配置文件：${result.opencodeRuntimeConfigPath}`
          : '配置已保存，并已清除 opencode 运行配置。请重启 opencode 容器使其回退到环境变量/内置配置；健康检查会在 opencode 实际生效配置与保存配置不一致时给出 warning。',
        latencyMs: null,
      } : null)
      setGatewayDraft({
        enabled: Boolean(result.config?.enabled),
        providerId: String(result.config?.providerId || ''),
        baseUrl: String(result.config?.baseUrl || result.config?.endpoint || ''),
        model: String(result.config?.model || ''),
        modelOptions: Array.isArray(result.config?.modelOptions) ? result.config.modelOptions : [],
        opencodeBaseUrl: String(result.config?.opencodeBaseUrl || ''),
        timeoutMs: Number(result.config?.timeoutMs || 30000),
        maxTokens: Number(result.config?.maxTokens || 4096),
        apiKey: '',
        apiKeyMasked: String(result.config?.apiKeyMasked || ''),
      })
      showToast(result.opencodeRestartRequired ? 'LLM 配置已保存，请重启 opencode 后生效' : 'LLM 模型配置已保存')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'LLM 模型配置保存失败'), 'error')
    } finally {
      setGatewaySaving(false)
    }
  }

  const handleTestGateway = async () => {
    setGatewayTesting(true)
    setGatewayTestResult(null)
    try {
      const result = await settingsAPI.gateway.test({
        providerId: gatewayDraft.providerId.trim(),
        baseUrl: gatewayDraft.baseUrl.trim(),
        model: gatewayDraft.model.trim(),
        modelId: gatewayDraft.model.trim(),
        opencodeBaseUrl: gatewayDraft.opencodeBaseUrl.trim(),
        timeoutMs: Number(gatewayDraft.timeoutMs || 0),
        ...(gatewayDraft.apiKey.trim() ? { apiKey: gatewayDraft.apiKey.trim() } : {}),
      })
      setGatewayTestResult({
        success: true,
        message: result.opencodeRestartRequired
          ? `${result.message} 如需用于目录生成，请保存配置并重启 opencode 容器。`
          : result.message,
        latencyMs: result.latencyMs,
      })
      showToast('LLM 模型连通性测试通过')
    } catch (e) {
      console.error(e)
      setGatewayTestResult({ success: false, message: safeMessage(e, 'LLM 模型测试失败'), latencyMs: null })
      showToast(safeMessage(e, 'LLM 模型测试失败'), 'error')
    } finally {
      setGatewayTesting(false)
    }
  }

  const handleSaveOcr = async () => {
    if (!ocrDirty) return
    setOcrSaving(true)
    try {
      const result = await settingsAPI.ocr.update({
        enabled: ocrDraft.enabled,
        baseUrl: ocrDraft.baseUrl.trim(),
        model: ocrDraft.model.trim(),
        timeoutMs: Number(ocrDraft.timeoutMs || 0),
        maxTokens: Number(ocrDraft.maxTokens || 0),
        ...(ocrDraft.apiKey.trim() ? { apiKey: ocrDraft.apiKey.trim() } : {}),
      })
      setOcr(result.config)
      setOcrDraft({
        enabled: Boolean(result.config?.enabled),
        baseUrl: String(result.config?.baseUrl || ''),
        model: String(result.config?.model || 'deepseek-ai/DeepSeek-OCR'),
        timeoutMs: Number(result.config?.timeoutMs || 60000),
        maxTokens: Number(result.config?.maxTokens || 2048),
        apiKey: '',
        apiKeyMasked: String(result.config?.apiKeyMasked || ''),
      })
      showToast('PDF/图片识别模型配置已保存')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'PDF/图片识别配置保存失败'), 'error')
    } finally {
      setOcrSaving(false)
    }
  }

  const handleTestOcr = async () => {
    setOcrTesting(true)
    setOcrTestResult(null)
    try {
      const result = await settingsAPI.ocr.test({
        baseUrl: ocrDraft.baseUrl.trim(),
        model: ocrDraft.model.trim(),
        timeoutMs: Number(ocrDraft.timeoutMs || 0),
        ...(ocrDraft.apiKey.trim() ? { apiKey: ocrDraft.apiKey.trim() } : {}),
      })
      setOcrTestResult({ success: true, message: result.message, latencyMs: result.latencyMs })
      showToast('PDF/图片识别模型连通性测试通过')
    } catch (e) {
      console.error(e)
      setOcrTestResult({ success: false, message: safeMessage(e, 'PDF/图片识别模型测试失败'), latencyMs: null })
      showToast(safeMessage(e, 'PDF/图片识别模型测试失败'), 'error')
    } finally {
      setOcrTesting(false)
    }
  }

  const handleUploadDefaultTemplate = async (file) => {
    if (!file) return
    setDefaultTemplateUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('fileName', file.name)
      formData.append('templateType', effectiveUploadType)
      formData.append('version', defaultTemplateUploadVersion || todayVersionLabel())
      const result = await settingsAPI.defaultTemplates.upload(formData)
      setDefaultTemplates(result.items || [])
      showToast('系统默认模板上传成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '系统默认模板上传失败'), 'error')
    } finally {
      setDefaultTemplateUploading(false)
    }
  }

  const handleActivateDefaultTemplate = async (id) => {
    setDefaultTemplateActivatingId(id)
    try {
      const result = await settingsAPI.defaultTemplates.activate(id)
      setDefaultTemplates(result.items || [])
      showToast('系统默认模板已启用')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '默认模板启用失败'), 'error')
    } finally {
      setDefaultTemplateActivatingId('')
    }
  }

  const handleDeleteDefaultTemplate = async (item) => {
    const ok = window.confirm(
      item.isActive
        ? `确认删除当前默认模板「${item.name}」？删除后将自动回退启用同类型最近的历史版本（如有）。`
        : `确认删除模板「${item.name}」？该操作不可恢复。`
    )
    if (!ok) return
    setDefaultTemplateDeletingId(item.id)
    try {
      const result = await settingsAPI.defaultTemplates.remove(item.id)
      setDefaultTemplates(result.items || [])
      showToast('系统默认模板已删除')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '默认模板删除失败'), 'error')
    } finally {
      setDefaultTemplateDeletingId('')
    }
  }

  if (loading && !gateway) {
    return <PageLoading title="正在加载设置中心…" description="正在同步系统核心配置。" />
  }

  if (error && !gateway) {
    return (
      <PageError
        title="设置中心加载失败"
        description={error}
        onRetry={() => loadAll()}
      />
    )
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-4">
      <PageHeader
        variant="panel"
        title="系统设置"
        description={(
          <>
            <span>管理默认 Word 模板、LLM、PDF/图片识别模型、用户与健康检查。</span>
            {refreshing && <span className="mt-1 block text-xs text-outline" role="status" aria-live="polite">正在刷新配置…</span>}
          </>
        )}
        actions={(
          <Button
            type="button"
            onClick={() => loadAll({ silent: true })}
            className="w-full sm:w-24"
            size="md"
            variant="secondary"
          >
            刷新
          </Button>
        )}
      />

      <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav aria-label="设置分类" className="flex min-w-0 items-center gap-1 overflow-x-auto rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-2 lg:block lg:self-start lg:overflow-visible lg:p-3">
          {['系统核心'].map((group) => (
            <div key={group} className="contents lg:block">
              <h2 className="mb-2 hidden px-2 text-xs font-semibold text-outline lg:block">{group}</h2>
              {sections.filter((item) => item.group === group).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveSection(item.id)}
                  aria-pressed={activeSection === item.id}
                  className={`flex min-h-11 shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary lg:mb-1 lg:min-h-10 lg:w-full ${
                    activeSection === item.id
                      ? 'border-outline-variant/70 bg-surface-container-low font-semibold text-on-surface'
                      : 'border-transparent text-on-surface-variant hover:border-outline-variant/60 hover:bg-surface-container-low hover:text-on-surface'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <section aria-label="设置内容" className="min-w-0 overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest lg:min-h-[32rem]">
          {activeSection === 'gateway' && (
            <div className="space-y-6 p-4 sm:p-5 lg:p-6">
              <div className="flex flex-col gap-3 border-b border-outline-variant pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="font-headline text-lg font-semibold text-on-surface">LLM 模型配置</h2>
                  <p className="text-sm text-on-surface-variant mt-1">维护 opencode 调用的 provider、model、Base URL 与 API Key。</p>
                </div>
                <label className="inline-flex min-h-11 items-center gap-2 text-sm text-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={gatewayDraft.enabled}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                  />
                  启用 LLM
                </label>
              </div>

              <div className="grid grid-cols-1 gap-x-5 gap-y-4 md:grid-cols-2 xl:grid-cols-3">
                <label className="text-sm text-on-surface-variant">
                  Provider ID
                  <input
                    value={gatewayDraft.providerId}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, providerId: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                    placeholder="opencode provider，例如 deepseek"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  Model ID
                  <input
                    list="llm-model-options"
                    value={gatewayDraft.model}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, model: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                    placeholder="DeepSeek 官方可填 deepseek-v4-flash"
                  />
                  <datalist id="llm-model-options">
                    {(gatewayDraft.modelOptions || []).map((item) => (
                      <option key={item.id || item.model || item} value={item.id || item.model || item}>
                        {item.label || item.name || item.id || item.model || item}
                      </option>
                    ))}
                  </datalist>
                </label>
                <label className="text-sm text-on-surface-variant">
                  Provider Base URL
                  <input
                    value={gatewayDraft.baseUrl}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, baseUrl: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                    placeholder="DeepSeek 官方填 https://api.deepseek.com"
                  />
                  <span className="mt-1 block text-xs text-outline">支持填写根地址、/v1 地址或完整 /chat/completions 地址。</span>
                </label>
                <label className="text-sm text-on-surface-variant">
                  OpenCode Base URL
                  <input
                    value={gatewayDraft.opencodeBaseUrl}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, opencodeBaseUrl: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                    placeholder="FastAPI 调用的 opencode 服务地址"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  API Key
                  <input
                    type="password"
                    value={gatewayDraft.apiKey}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                    placeholder={gatewayDraft.apiKeyMasked || '输入 API Key'}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                  <span className="mt-1 block text-xs text-outline">已保存 Key：{gatewayDraft.apiKeyMasked || '-'}</span>
                </label>
                <label className="text-sm text-on-surface-variant">
                  超时 (ms)
                  <input
                    type="number"
                    value={gatewayDraft.timeoutMs}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, timeoutMs: Number(event.target.value || 0) }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  Max Tokens
                  <input
                    type="number"
                    value={gatewayDraft.maxTokens}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, maxTokens: Number(event.target.value || 0) }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                </label>
              </div>

              <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-3 text-xs leading-5 text-outline">
                当前生效：Provider ID {gatewayDraft.providerId || '-'} · Model ID {gatewayDraft.model || '-'} · Provider Base URL {gatewayDraft.baseUrl || '-'} · OpenCode Base URL {gatewayDraft.opencodeBaseUrl || '-'} · API Key {gatewayDraft.apiKeyMasked || '-'} · 最近更新：{gateway?.updatedAt || '-'} / {gateway?.updatedBy || '-'}
              </div>
              <div className="rounded border border-amber-200 bg-amber-50/60 px-4 py-3 text-xs leading-6 text-amber-950">
                说明：连接测试会验证 Provider 直连能力；目录生成实际走 FastAPI → opencode → Provider。保存 LLM 配置后需要重启 opencode 容器，opencode 才会加载新的 provider/model。
              </div>

              {gatewayTestResult && (
                <div className={`rounded-lg p-3 text-sm border ${
                  gatewayTestResult.success
                    ? 'bg-secondary-container/30 border-secondary/30 text-secondary'
                    : 'bg-error-container/20 border-error/30 text-error'
                }`}>
                  {gatewayTestResult.message}
                  {gatewayTestResult.latencyMs ? `（${gatewayTestResult.latencyMs}ms）` : ''}
                </div>
              )}

              <div className="flex flex-col-reverse justify-end gap-2 sm:flex-row sm:gap-3">
                <Button
                  type="button"
                  onClick={handleTestGateway}
                  disabled={gatewayTesting}
                  className="w-full sm:w-28"
                  size="md"
                  variant="secondary"
                >
                  {gatewayTesting ? '测试中…' : '连接测试'}
                </Button>
                <Button
                  type="button"
                  onClick={handleSaveGateway}
                  disabled={!gatewayDirty || gatewaySaving}
                  className="w-full sm:w-28"
                  size="md"
                  variant="primary"
                >
                  {gatewaySaving ? '保存中…' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'ocr' && (
            <div className="space-y-6 p-4 sm:p-5 lg:p-6">
              <div className="flex flex-col gap-3 border-b border-outline-variant pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="font-headline text-lg font-semibold text-on-surface">PDF/图片识别模型配置</h2>
                  <p className="text-sm text-on-surface-variant mt-1">维护扫描件、图片型 PDF 和图片识别所用模型。</p>
                </div>
                <label className="inline-flex min-h-11 items-center gap-2 text-sm text-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={ocrDraft.enabled}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                  />
                  启用识别模型
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="text-sm text-on-surface-variant">
                  Base URL
                  <input
                    value={ocrDraft.baseUrl}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, baseUrl: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  模型
                  <input
                    value={ocrDraft.model}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, model: event.target.value }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  API Key
                  <input
                    type="password"
                    value={ocrDraft.apiKey}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                    placeholder={ocrDraft.apiKeyMasked || '输入 API Key'}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                  <span className="mt-1 block text-xs text-outline">已保存 Key：{ocrDraft.apiKeyMasked || '-'}</span>
                </label>
                <label className="text-sm text-on-surface-variant">
                  超时 (ms)
                  <input
                    type="number"
                    value={ocrDraft.timeoutMs}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, timeoutMs: Number(event.target.value || 0) }))}
                    className="mt-1 min-h-11 w-full rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:text-sm"
                  />
                </label>
              </div>

              <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-3 text-xs leading-5 text-outline">
                Base URL：{ocrDraft.baseUrl || '-'} · 模型：{ocrDraft.model || '-'} · API Key：{ocrDraft.apiKeyMasked || '-'} · 最近更新：{ocr?.updatedAt || '-'} / {ocr?.updatedBy || '-'}
              </div>

              {ocrTestResult && (
                <div className={`rounded-lg p-3 text-sm border ${
                  ocrTestResult.success
                    ? 'bg-secondary-container/30 border-secondary/30 text-secondary'
                    : 'bg-error-container/20 border-error/30 text-error'
                }`}>
                  {ocrTestResult.message}
                  {ocrTestResult.latencyMs ? `（${ocrTestResult.latencyMs}ms）` : ''}
                </div>
              )}

              <div className="flex flex-col-reverse justify-end gap-2 sm:flex-row sm:gap-3">
                <Button
                  type="button"
                  onClick={handleTestOcr}
                  disabled={ocrTesting}
                  className="w-full sm:w-28"
                  size="md"
                  variant="secondary"
                >
                  {ocrTesting ? '测试中…' : '连接测试'}
                </Button>
                <Button
                  type="button"
                  onClick={handleSaveOcr}
                  disabled={!ocrDirty || ocrSaving}
                  className="w-full sm:w-28"
                  size="md"
                  variant="primary"
                >
                  {ocrSaving ? '保存中…' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'defaultTemplates' && (
            <div className="space-y-5 p-4 sm:p-5 lg:p-6">
              <div className="flex flex-col gap-4 border-b border-outline-variant pb-5 xl:flex-row xl:items-end xl:justify-between">
                <div>
                  <h2 className="font-headline text-lg font-semibold text-on-surface">系统默认模板</h2>
                  <p className="text-sm text-on-surface-variant mt-1">项目未上传模板时，自动使用这里启用的默认模板。</p>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[auto_minmax(9rem,1fr)_auto]">
                  <select
                    aria-label="模板类型"
                    value={effectiveUploadType}
                    onChange={(event) => setDefaultTemplateUploadType(event.target.value)}
                    disabled={visibleTemplateTypes.length <= 1}
                    className="h-11 rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface disabled:opacity-60 sm:text-sm"
                  >
                    {visibleTemplateTypes.map((item) => (
                      <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                  </select>
                  <input
                    aria-label="模板版本"
                    value={defaultTemplateUploadVersion}
                    onChange={(event) => setDefaultTemplateUploadVersion(event.target.value)}
                    className="h-11 min-w-0 rounded-md border border-outline-variant bg-white px-3 text-base text-on-surface sm:text-sm"
                    placeholder="版本…"
                  />
                  <input
                    ref={defaultTemplateFileInputRef}
                    type="file"
                    accept=".docx"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) handleUploadDefaultTemplate(file)
                      event.target.value = ''
                    }}
                  />
                  <Button
                    type="button"
                    onClick={() => defaultTemplateFileInputRef.current?.click()}
                    disabled={defaultTemplateUploading}
                    className="w-full sm:w-40"
                    size="md"
                    variant="primary"
                  >
                    {defaultTemplateUploading ? '上传中…' : '上传默认模板'}
                  </Button>
                </div>
              </div>

              {!visibleDefaultTemplates.length ? (
                <PageEmpty title="暂无系统默认模板" description="请上传技术标或商务标默认模板。" />
              ) : (
                <div className="overflow-x-auto rounded border border-outline-variant">
                  <table className="w-full min-w-[48rem] text-sm">
                    <thead>
                      <tr className="border-b border-outline-variant bg-surface-container-low">
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">类型</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">模板名称</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">版本</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">上传信息</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">状态</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleDefaultTemplates.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/50">
                          <td className="px-3 py-3">{item.templateTypeLabel}</td>
                          <td className="px-3 py-3 text-on-surface">{item.name}</td>
                          <td className="px-3 py-3 font-mono text-xs">{item.version}</td>
                          <td className="px-3 py-3 text-xs text-outline">{item.uploadedBy} · {item.uploadedAt}</td>
                          <td className="px-3 py-3">
                            {item.isActive ? (
                              <span className="text-xs px-2 py-1 rounded bg-secondary-container text-on-secondary-container">默认生效</span>
                            ) : (
                              <span className="text-xs px-2 py-1 rounded bg-surface-container-high text-on-surface-variant">未生效</span>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center gap-3">
                              <button
                                type="button"
                                onClick={() => handleActivateDefaultTemplate(item.id)}
                                disabled={item.isActive || defaultTemplateActivatingId === item.id}
                                className="min-h-11 rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {defaultTemplateActivatingId === item.id ? '启用中…' : item.isActive ? '当前默认' : '设为默认'}
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDeleteDefaultTemplate(item)}
                                disabled={defaultTemplateDeletingId === item.id}
                                className="min-h-11 rounded-md px-2 text-xs font-semibold text-error hover:bg-error-container/30 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {defaultTemplateDeletingId === item.id ? '删除中…' : '删除'}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {activeSection === 'health' && (
            <div className="space-y-5 p-4 sm:p-5 lg:p-6">
              <div className="border-b border-outline-variant pb-5">
                <h2 className="font-headline text-lg font-semibold text-on-surface">系统健康</h2>
                <p className="text-sm text-on-surface-variant mt-1">实时查看核心服务状态与延迟。</p>
              </div>
              {!health.length ? (
                <PageEmpty title="暂无健康数据" description="请稍后重试刷新。" />
              ) : (
                <div className="grid grid-cols-1 overflow-hidden rounded border border-outline-variant md:grid-cols-2">
                  {health.map((item, index) => (
                    <div key={item.id || `${item.name}-${index}`} className="border-b border-outline-variant p-4 last:border-b-0 md:border-r md:[&:nth-child(even)]:border-r-0 md:[&:nth-last-child(-n+2)]:border-b-0">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-on-surface">{item.name || '-'}</h3>
                        <span className={`text-xs px-2 py-1 rounded-full ${
                          item.status === 'online'
                            ? 'bg-secondary-container text-on-secondary-container'
                            : 'bg-error-container text-on-error-container'
                        }`}>
                          {item.status === 'online' ? '在线' : '离线'}
                        </span>
                      </div>
                      <p className="text-xs text-outline mt-2">可用性：{item.uptime || '-'}</p>
                      <p className="text-xs text-outline mt-1">延迟：{item.latency || '-'}</p>
                      <p className="text-xs text-on-surface-variant mt-2">{item.detail || '暂无详情'}</p>
                      {item.warning && (
                        <p className="text-xs text-amber-700 mt-1">{item.warning}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'users' && (
            <div className="space-y-5 p-4 sm:p-5 lg:p-6">
              <div className="border-b border-outline-variant pb-5">
                <h2 className="font-headline text-lg font-semibold text-on-surface">用户</h2>
                <p className="text-sm text-on-surface-variant mt-1">查看系统账户、部门、角色和状态。</p>
              </div>
              {!users.length ? (
                <PageEmpty title="暂无用户数据" description="请检查用户同步接口。" />
              ) : (
                <div className="overflow-x-auto rounded border border-outline-variant">
                  <table className="w-full min-w-[40rem] text-sm">
                    <thead>
                      <tr className="border-b border-outline-variant bg-surface-container-low">
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">用户</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">部门</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">角色</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-semibold text-on-surface-variant">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/50">
                          <td className="px-3 py-3">
                            <div className="font-medium text-on-surface">{item.name}</div>
                            <div className="break-all text-xs text-outline">{item.email}</div>
                          </td>
                          <td className="px-3 py-3">{item.dept}</td>
                          <td className="px-3 py-3 text-xs">{(item.roles || []).join('、')}</td>
                          <td className="px-3 py-3">{item.status === 'active' ? '正常' : '离线'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
