import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { settingsAPI } from '../api'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const deepEqualByKeys = (left, right, keys) =>
  keys.every((key) => JSON.stringify(left?.[key]) === JSON.stringify(right?.[key]))

export default function Settings({ showToast = () => {} }) {
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
  const [defaultTemplateUploadVersion, setDefaultTemplateUploadVersion] = useState('2026.05')
  const [defaultTemplateUploading, setDefaultTemplateUploading] = useState(false)
  const [defaultTemplateActivatingId, setDefaultTemplateActivatingId] = useState('')

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
    { id: 'ocr', icon: 'document_scanner', label: 'OCR 模型', group: '系统核心' },
    { id: 'users', icon: 'group', label: '用户', group: '系统核心' },
    { id: 'audit', icon: 'history', label: '审计', group: '系统核心' },
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
      showToast('LLM 模型配置已保存')
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
      setGatewayTestResult({ success: true, message: result.message, latencyMs: result.latencyMs })
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
      showToast('OCR 模型配置已保存')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'OCR 配置保存失败'), 'error')
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
      showToast('OCR 连通性测试通过')
    } catch (e) {
      console.error(e)
      setOcrTestResult({ success: false, message: safeMessage(e, 'OCR 测试失败'), latencyMs: null })
      showToast(safeMessage(e, 'OCR 测试失败'), 'error')
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
      formData.append('templateType', defaultTemplateUploadType)
      formData.append('version', defaultTemplateUploadVersion || '2026.05')
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

  if (loading && !gateway) {
    return <PageLoading title="正在加载设置中心..." description="正在同步系统核心配置。" />
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
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-3">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">系统设置</h1>
          <p className="text-sm text-on-surface-variant mt-1">管理默认 Word 模板、LLM/OCR 模型、用户、审计与健康检查。</p>
          {refreshing && <p className="text-xs text-outline mt-1">正在刷新配置...</p>}
        </div>
        <button
          onClick={() => loadAll({ silent: true })}
          className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-sm">refresh</span>
          刷新全部模块
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] p-4">
          {['系统核心'].map((group) => (
            <div key={group} className="mb-4">
              <h4 className="text-xs font-semibold text-outline uppercase tracking-wider px-3 mb-2">{group}</h4>
              {sections.filter((item) => item.group === group).map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                    activeSection === item.id
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-on-surface-variant hover:bg-surface-container-low'
                  }`}
                >
                  <span className="material-symbols-outlined text-lg">{item.icon}</span>
                  {item.label}
                  {activeSection === item.id && <span className="material-symbols-outlined text-sm ml-auto">chevron_right</span>}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div className="lg:col-span-3 bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] overflow-hidden">
          {activeSection === 'gateway' && (
            <div className="p-6 space-y-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">LLM 模型配置</h2>
                  <p className="text-sm text-on-surface-variant mt-1">维护 opencode 调用的 provider、model、Base URL 与 API Key。</p>
                </div>
                <label className="inline-flex items-center gap-2 text-sm text-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={gatewayDraft.enabled}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                  />
                  启用 LLM
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="text-sm text-on-surface-variant">
                  Provider ID
                  <input
                    value={gatewayDraft.providerId}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, providerId: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                    placeholder="opencode provider，例如 mimo"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  Model ID
                  <input
                    list="llm-model-options"
                    value={gatewayDraft.model}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, model: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                    placeholder="opencode model，例如 mimo-v2.5"
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
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                    placeholder="OpenAI-compatible /v1 地址"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  OpenCode Base URL
                  <input
                    value={gatewayDraft.opencodeBaseUrl}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, opencodeBaseUrl: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                    placeholder="FastAPI 调用的 opencode 服务地址"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  API Key
                  <input
                    type="password"
                    value={gatewayDraft.apiKey}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                    placeholder={gatewayDraft.apiKeyMasked ? '保持当前 Key 不变' : '输入 API Key'}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  超时 (ms)
                  <input
                    type="number"
                    value={gatewayDraft.timeoutMs}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, timeoutMs: Number(event.target.value || 0) }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  Max Tokens
                  <input
                    type="number"
                    value={gatewayDraft.maxTokens}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, maxTokens: Number(event.target.value || 0) }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
              </div>

              <div className="rounded-lg bg-surface-container-low p-3 text-xs text-outline">
                当前生效：{gatewayDraft.providerId || '-'}/{gatewayDraft.model || '-'} · API Key：{gatewayDraft.apiKeyMasked || '-'} · 最近更新：{gateway?.updatedAt || '-'} / {gateway?.updatedBy || '-'}
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

              <div className="flex justify-end gap-3">
                <button
                  onClick={handleTestGateway}
                  disabled={gatewayTesting}
                  className="px-4 py-2 text-sm font-medium text-on-surface-variant bg-surface-container-high hover:bg-surface-dim rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {gatewayTesting ? '测试中...' : '连接测试'}
                </button>
                <button
                  onClick={handleSaveGateway}
                  disabled={!gatewayDirty || gatewaySaving}
                  className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {gatewaySaving ? '保存中...' : '保存配置'}
                </button>
              </div>
            </div>
          )}

          {activeSection === 'ocr' && (
            <div className="p-6 space-y-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">OCR 模型配置</h2>
                  <p className="text-sm text-on-surface-variant mt-1">维护图片型 PDF 和图片识别所用模型。</p>
                </div>
                <label className="inline-flex items-center gap-2 text-sm text-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={ocrDraft.enabled}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                  />
                  启用 OCR
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="text-sm text-on-surface-variant">
                  Base URL
                  <input
                    value={ocrDraft.baseUrl}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, baseUrl: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  模型
                  <input
                    value={ocrDraft.model}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, model: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  API Key
                  <input
                    type="password"
                    value={ocrDraft.apiKey}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                    placeholder={ocrDraft.apiKeyMasked ? '保持当前 Key 不变' : '输入 API Key'}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  超时 (ms)
                  <input
                    type="number"
                    value={ocrDraft.timeoutMs}
                    onChange={(event) => setOcrDraft((prev) => ({ ...prev, timeoutMs: Number(event.target.value || 0) }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
              </div>

              <div className="rounded-lg bg-surface-container-low p-3 text-xs text-outline">
                API Key：{ocrDraft.apiKeyMasked || '-'} · 最近更新：{ocr?.updatedAt || '-'} / {ocr?.updatedBy || '-'}
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

              <div className="flex justify-end gap-3">
                <button
                  onClick={handleTestOcr}
                  disabled={ocrTesting}
                  className="px-4 py-2 text-sm font-medium text-on-surface-variant bg-surface-container-high hover:bg-surface-dim rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {ocrTesting ? '测试中...' : '连接测试'}
                </button>
                <button
                  onClick={handleSaveOcr}
                  disabled={!ocrDirty || ocrSaving}
                  className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {ocrSaving ? '保存中...' : '保存配置'}
                </button>
              </div>
            </div>
          )}

          {activeSection === 'defaultTemplates' && (
            <div className="p-6 space-y-5">
              <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">系统默认模板</h2>
                  <p className="text-sm text-on-surface-variant mt-1">项目未上传模板时，自动使用这里启用的默认模板。</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={defaultTemplateUploadType}
                    onChange={(event) => setDefaultTemplateUploadType(event.target.value)}
                    className="h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm"
                  >
                    {defaultTemplateTypes.map((item) => (
                      <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                  </select>
                  <input
                    value={defaultTemplateUploadVersion}
                    onChange={(event) => setDefaultTemplateUploadVersion(event.target.value)}
                    className="h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm w-32"
                    placeholder="版本"
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
                  <button
                    onClick={() => defaultTemplateFileInputRef.current?.click()}
                    disabled={defaultTemplateUploading}
                    className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {defaultTemplateUploading ? '上传中...' : '上传默认模板'}
                  </button>
                </div>
              </div>

              {!defaultTemplates.length ? (
                <PageEmpty title="暂无系统默认模板" description="请上传技术标或商务标默认模板。" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-container-high">
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">类型</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">模板名称</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">版本</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">上传信息</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">状态</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {defaultTemplates.map((item) => (
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
                            <button
                              onClick={() => handleActivateDefaultTemplate(item.id)}
                              disabled={item.isActive || defaultTemplateActivatingId === item.id}
                              className="text-xs text-primary hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {defaultTemplateActivatingId === item.id ? '启用中...' : item.isActive ? '当前默认' : '设为默认'}
                            </button>
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
            <div className="p-6 space-y-4">
              <div className="flex justify-between items-center">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">系统健康</h2>
                  <p className="text-sm text-on-surface-variant mt-1">实时查看核心服务状态与延迟。</p>
                </div>
                <button
                  onClick={() => loadAll({ silent: true })}
                  className="px-3 py-2 text-xs rounded-lg bg-surface-container-high hover:bg-surface-dim text-on-surface-variant"
                >
                  刷新状态
                </button>
              </div>
              {!health.length ? (
                <PageEmpty title="暂无健康数据" description="请稍后重试刷新。" />
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {health.map((item, index) => (
                    <div key={item.id || `${item.name}-${index}`} className="rounded-xl border border-surface-container-high p-4">
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
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'audit' && (
            <div className="p-6 space-y-5">
              <div>
                <h2 className="text-lg font-headline font-bold text-on-surface">审计</h2>
                <p className="text-sm text-on-surface-variant mt-1">查看登录、配置、OCR、素材和生成标书过程中的操作记录。</p>
              </div>
              <div className="rounded-xl border border-surface-container-high p-4 bg-surface-container-low">
                <div className="text-sm font-semibold text-on-surface">审计日志</div>
                <p className="text-xs text-on-surface-variant mt-1">日志页面支持按用户、模块、动作、状态和关键字筛选，并可查看 diff 与元数据。</p>
                <Link
                  to="/audit"
                  className="inline-flex items-center gap-2 mt-4 px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg"
                >
                  <span className="material-symbols-outlined text-sm">open_in_new</span>
                  打开审计日志
                </Link>
              </div>
            </div>
          )}

          {activeSection === 'users' && (
            <div className="p-6 space-y-4">
              <div>
                <h2 className="text-lg font-headline font-bold text-on-surface">用户</h2>
                <p className="text-sm text-on-surface-variant mt-1">查看系统账户、部门、角色和状态。</p>
              </div>
              {!users.length ? (
                <PageEmpty title="暂无用户数据" description="请检查用户同步接口。" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-container-high">
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">用户</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">部门</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">角色</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/50">
                          <td className="px-3 py-3">
                            <div className="font-medium text-on-surface">{item.name}</div>
                            <div className="text-xs text-outline">{item.email}</div>
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
        </div>
      </div>
    </div>
  )
}
