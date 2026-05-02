import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { settingsAPI } from '../api'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const deepEqualByKeys = (left, right, keys) =>
  keys.every((key) => JSON.stringify(left?.[key]) === JSON.stringify(right?.[key]))

export default function Settings({ showToast = () => {} }) {
  const [activeSection, setActiveSection] = useState('gateway')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [users, setUsers] = useState([])
  const [gateway, setGateway] = useState(null)
  const [gatewayDraft, setGatewayDraft] = useState({
    enabled: true,
    endpoint: '',
    baseUrl: '',
    model: '',
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

  const [dotxTemplates, setDotxTemplates] = useState([])
  const [dotxUploading, setDotxUploading] = useState(false)
  const [dotxActivatingId, setDotxActivatingId] = useState('')

  const [excelTemplates, setExcelTemplates] = useState([])
  const [excelTableOptions, setExcelTableOptions] = useState([])
  const [excelUploadTableKey, setExcelUploadTableKey] = useState('')
  const [excelUploadVersion, setExcelUploadVersion] = useState('')
  const [excelUploading, setExcelUploading] = useState(false)
  const [excelActivatingId, setExcelActivatingId] = useState('')

  const [backups, setBackups] = useState([])
  const [backupNote, setBackupNote] = useState('')
  const [backupCreating, setBackupCreating] = useState(false)
  const [backupRestoringId, setBackupRestoringId] = useState('')
  const [latestRestoreAt, setLatestRestoreAt] = useState('')

  const [health, setHealth] = useState([])

  const dotxFileInputRef = useRef(null)
  const excelFileInputRef = useRef(null)
  const defaultTemplateFileInputRef = useRef(null)

  const loadAll = useCallback(async (options = {}) => {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError('')

    try {
      const [usersRes, gatewayRes, ocrRes, defaultTemplatesRes, dotxRes, excelRes, backupsRes, healthRes] = await Promise.all([
        settingsAPI.users.list(),
        settingsAPI.gateway.get(),
        settingsAPI.ocr.get(),
        settingsAPI.defaultTemplates.list(),
        settingsAPI.dotxTemplates.list(),
        settingsAPI.excelTemplates.list(),
        settingsAPI.backups.list(),
        settingsAPI.health(),
      ])
      setUsers(usersRes?.items || [])
      setGateway(gatewayRes || null)
      setGatewayDraft({
        enabled: Boolean(gatewayRes?.enabled),
        endpoint: String(gatewayRes?.endpoint || gatewayRes?.baseUrl || ''),
        baseUrl: String(gatewayRes?.baseUrl || gatewayRes?.endpoint || ''),
        model: String(gatewayRes?.model || ''),
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
      setDotxTemplates(dotxRes?.items || [])
      setExcelTemplates(excelRes?.items || [])
      const optionsList = excelRes?.tableOptions || []
      setExcelTableOptions(optionsList)
      setExcelUploadTableKey((prev) => {
        if (prev && optionsList.some((item) => item.key === prev)) return prev
        return optionsList[0]?.key || ''
      })
      setBackups(backupsRes?.items || [])
      setLatestRestoreAt(backupsRes?.latestRestoreAt || '')
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
    { id: 'gateway', icon: 'hub', label: 'LLM 网关', group: '系统核心' },
    { id: 'defaultTemplates', icon: 'description', label: '默认模板', group: '系统核心' },
    { id: 'ocr', icon: 'document_scanner', label: 'OCR 模型', group: '系统核心' },
    { id: 'dotx', icon: 'format_shapes', label: '.dotx 样式模板', group: '系统核心' },
    { id: 'excel', icon: 'table_chart', label: 'Excel 模板版本', group: '系统核心' },
    { id: 'backup', icon: 'database', label: '备份与恢复', group: '系统核心' },
    { id: 'health', icon: 'monitor_heart', label: '系统健康', group: '系统核心' },
    { id: 'users', icon: 'group', label: '用户与角色', group: '账户与权限' },
  ]

  const gatewayDirty = useMemo(() => {
    if (!gateway) return false
    return !deepEqualByKeys(gatewayDraft, gateway, ['enabled', 'baseUrl', 'model', 'timeoutMs', 'maxTokens'])
      || Boolean(gatewayDraft.apiKey.trim())
  }, [gateway, gatewayDraft])

  const ocrDirty = useMemo(() => {
    if (!ocr) return false
    return !deepEqualByKeys(ocrDraft, ocr, ['enabled', 'baseUrl', 'model', 'timeoutMs', 'maxTokens'])
      || Boolean(ocrDraft.apiKey.trim())
  }, [ocr, ocrDraft])

  const activeDotxId = useMemo(
    () => dotxTemplates.find((item) => item.isActive)?.id || '',
    [dotxTemplates],
  )

  const groupedExcelTemplates = useMemo(() => {
    const grouped = {}
    excelTemplates.forEach((item) => {
      if (!grouped[item.tableKey]) grouped[item.tableKey] = []
      grouped[item.tableKey].push(item)
    })
    return grouped
  }, [excelTemplates])

  const handleSaveGateway = async () => {
    if (!gatewayDirty) return
    setGatewaySaving(true)
    try {
      const result = await settingsAPI.gateway.update({
        enabled: gatewayDraft.enabled,
        baseUrl: (gatewayDraft.baseUrl || gatewayDraft.endpoint).trim(),
        endpoint: (gatewayDraft.baseUrl || gatewayDraft.endpoint).trim(),
        model: gatewayDraft.model.trim(),
        timeoutMs: Number(gatewayDraft.timeoutMs || 0),
        maxTokens: Number(gatewayDraft.maxTokens || 0),
        ...(gatewayDraft.apiKey.trim() ? { apiKey: gatewayDraft.apiKey.trim() } : {}),
      })
      setGateway(result.config)
      setGatewayDraft({
        enabled: Boolean(result.config?.enabled),
        endpoint: String(result.config?.endpoint || result.config?.baseUrl || ''),
        baseUrl: String(result.config?.baseUrl || result.config?.endpoint || ''),
        model: String(result.config?.model || ''),
        timeoutMs: Number(result.config?.timeoutMs || 30000),
        maxTokens: Number(result.config?.maxTokens || 4096),
        apiKey: '',
        apiKeyMasked: String(result.config?.apiKeyMasked || ''),
      })
      showToast('LLM 网关配置已保存')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '网关配置保存失败'), 'error')
    } finally {
      setGatewaySaving(false)
    }
  }

  const handleTestGateway = async () => {
    setGatewayTesting(true)
    setGatewayTestResult(null)
    try {
      const result = await settingsAPI.gateway.test({
        baseUrl: (gatewayDraft.baseUrl || gatewayDraft.endpoint).trim(),
        endpoint: (gatewayDraft.baseUrl || gatewayDraft.endpoint).trim(),
        model: gatewayDraft.model.trim(),
        timeoutMs: Number(gatewayDraft.timeoutMs || 0),
        ...(gatewayDraft.apiKey.trim() ? { apiKey: gatewayDraft.apiKey.trim() } : {}),
      })
      setGatewayTestResult({ success: true, message: result.message, latencyMs: result.latencyMs })
      showToast('网关连通性测试通过')
    } catch (e) {
      console.error(e)
      setGatewayTestResult({ success: false, message: safeMessage(e, '网关测试失败'), latencyMs: null })
      showToast(safeMessage(e, '网关测试失败'), 'error')
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

  const handleUploadDotx = async (file) => {
    if (!file) return
    setDotxUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('fileName', file.name)
      formData.append('fileSize', String(file.size))
      formData.append('version', excelUploadVersion || '2026.04')
      const result = await settingsAPI.dotxTemplates.upload(formData)
      setDotxTemplates(result.items || [])
      showToast('dotx 模板上传成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'dotx 模板上传失败'), 'error')
    } finally {
      setDotxUploading(false)
    }
  }

  const handleActivateDotx = async (id) => {
    setDotxActivatingId(id)
    try {
      const result = await settingsAPI.dotxTemplates.activate(id)
      setDotxTemplates(result.items || [])
      showToast('已切换当前生效的 dotx 模板')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'dotx 模板激活失败'), 'error')
    } finally {
      setDotxActivatingId('')
    }
  }

  const handleUploadExcelTemplate = async (file) => {
    if (!file) return
    if (!excelUploadTableKey) {
      showToast('请先选择模板归属数据表', 'error')
      return
    }
    setExcelUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('tableKey', excelUploadTableKey)
      formData.append('fileName', file.name)
      if (excelUploadVersion.trim()) {
        formData.append('version', excelUploadVersion.trim())
      }
      const result = await settingsAPI.excelTemplates.upload(formData)
      setExcelTemplates(result.items || [])
      showToast('Excel 模板版本上传成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, 'Excel 模板上传失败'), 'error')
    } finally {
      setExcelUploading(false)
    }
  }

  const handleActivateExcelTemplate = async (id) => {
    setExcelActivatingId(id)
    try {
      const result = await settingsAPI.excelTemplates.activate(id)
      setExcelTemplates(result.items || [])
      showToast('模板版本切换成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '模板激活失败'), 'error')
    } finally {
      setExcelActivatingId('')
    }
  }

  const handleCreateBackup = async () => {
    setBackupCreating(true)
    try {
      const result = await settingsAPI.backups.create({ note: backupNote.trim() })
      setBackups(result.items || [])
      setBackupNote('')
      showToast('备份创建成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '创建备份失败'), 'error')
    } finally {
      setBackupCreating(false)
    }
  }

  const handleRestoreBackup = async (id) => {
    setBackupRestoringId(id)
    try {
      const result = await settingsAPI.backups.restore(id)
      setBackups(result.items || [])
      setLatestRestoreAt(result.item?.restoredAt || latestRestoreAt)
      showToast('备份恢复完成')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '恢复备份失败'), 'error')
    } finally {
      setBackupRestoringId('')
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
          <p className="text-sm text-on-surface-variant mt-1">已接入企业部署核心模块：网关、模板、备份、健康检查。</p>
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
          {['系统核心', '账户与权限'].map((group) => (
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
                  <h2 className="text-lg font-headline font-bold text-on-surface">LLM 网关配置</h2>
                  <p className="text-sm text-on-surface-variant mt-1">维护网关地址、默认模型与超时策略。</p>
                </div>
                <label className="inline-flex items-center gap-2 text-sm text-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={gatewayDraft.enabled}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, enabled: event.target.checked }))}
                  />
                  启用网关
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="text-sm text-on-surface-variant">
                  Base URL
                  <input
                    value={gatewayDraft.baseUrl || gatewayDraft.endpoint}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, baseUrl: event.target.value, endpoint: event.target.value }))}
                    className="mt-1 w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
                  />
                </label>
                <label className="text-sm text-on-surface-variant">
                  默认模型
                  <input
                    value={gatewayDraft.model}
                    onChange={(event) => setGatewayDraft((prev) => ({ ...prev, model: event.target.value }))}
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
                API Key：{gatewayDraft.apiKeyMasked || '-'} · 最近更新：{gateway?.updatedAt || '-'} / {gateway?.updatedBy || '-'}
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
                    accept=".docx,.dotx"
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

          {activeSection === 'dotx' && (
            <div className="p-6 space-y-4">
              <div className="flex justify-between items-center gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">.dotx 样式模板</h2>
                  <p className="text-sm text-on-surface-variant mt-1">管理导出格式标准模板，切换当前生效版本。</p>
                </div>
                <input
                  ref={dotxFileInputRef}
                  type="file"
                  accept=".dotx"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) handleUploadDotx(file)
                    event.target.value = ''
                  }}
                />
                <button
                  onClick={() => dotxFileInputRef.current?.click()}
                  disabled={dotxUploading}
                  className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {dotxUploading ? '上传中...' : '上传 dotx 模板'}
                </button>
              </div>

              {!dotxTemplates.length ? (
                <PageEmpty title="暂无 dotx 模板" description="请先上传模板文件。" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-container-high">
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">模板名称</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">版本</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">上传信息</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">状态</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dotxTemplates.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/50">
                          <td className="px-3 py-3 text-on-surface">{item.name}</td>
                          <td className="px-3 py-3 font-mono text-xs">{item.version}</td>
                          <td className="px-3 py-3 text-xs text-outline">{item.uploadedBy} · {item.uploadedAt}</td>
                          <td className="px-3 py-3">
                            {item.isActive ? (
                              <span className="text-xs px-2 py-1 rounded bg-secondary-container text-on-secondary-container">生效中</span>
                            ) : (
                              <span className="text-xs px-2 py-1 rounded bg-surface-container-high text-on-surface-variant">未生效</span>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <button
                              onClick={() => handleActivateDotx(item.id)}
                              disabled={item.id === activeDotxId || dotxActivatingId === item.id}
                              className="text-xs text-primary hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {dotxActivatingId === item.id ? '切换中...' : item.id === activeDotxId ? '当前版本' : '设为生效'}
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

          {activeSection === 'excel' && (
            <div className="p-6 space-y-5">
              <div className="flex justify-between items-end gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">Excel 模板版本管理</h2>
                  <p className="text-sm text-on-surface-variant mt-1">按数据表管理导入模板版本，并支持激活切换。</p>
                </div>
                <div className="flex gap-2">
                  <select
                    value={excelUploadTableKey}
                    onChange={(event) => setExcelUploadTableKey(event.target.value)}
                    className="h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm"
                  >
                    {excelTableOptions.map((item) => (
                      <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                  </select>
                  <input
                    value={excelUploadVersion}
                    onChange={(event) => setExcelUploadVersion(event.target.value)}
                    placeholder="版本号（可选）"
                    className="h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm w-36"
                  />
                  <input
                    ref={excelFileInputRef}
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) handleUploadExcelTemplate(file)
                      event.target.value = ''
                    }}
                  />
                  <button
                    onClick={() => excelFileInputRef.current?.click()}
                    disabled={excelUploading}
                    className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {excelUploading ? '上传中...' : '上传模板版本'}
                  </button>
                </div>
              </div>

              {!excelTemplates.length ? (
                <PageEmpty title="暂无 Excel 模板版本" description="请先上传模板版本文件。" />
              ) : (
                <div className="space-y-4">
                  {Object.entries(groupedExcelTemplates).map(([tableKey, versions]) => (
                    <div key={tableKey} className="rounded-xl border border-surface-container-high overflow-hidden">
                      <div className="px-4 py-2 bg-surface-container-low text-sm font-semibold text-on-surface">
                        {versions[0]?.tableLabel || tableKey}
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-surface-container-high/60">
                              <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">版本</th>
                              <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">文件名</th>
                              <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">上传信息</th>
                              <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">状态</th>
                              <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {versions.map((item) => (
                              <tr key={item.id} className="border-b border-surface-container-high/50">
                                <td className="px-3 py-3 font-mono text-xs">{item.version}</td>
                                <td className="px-3 py-3">{item.fileName}</td>
                                <td className="px-3 py-3 text-xs text-outline">{item.uploadedBy} · {item.uploadedAt}</td>
                                <td className="px-3 py-3">
                                  {item.isActive ? (
                                    <span className="text-xs px-2 py-1 rounded bg-secondary-container text-on-secondary-container">生效中</span>
                                  ) : (
                                    <span className="text-xs px-2 py-1 rounded bg-surface-container-high text-on-surface-variant">未生效</span>
                                  )}
                                </td>
                                <td className="px-3 py-3">
                                  <button
                                    onClick={() => handleActivateExcelTemplate(item.id)}
                                    disabled={item.isActive || excelActivatingId === item.id}
                                    className="text-xs text-primary hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                                  >
                                    {excelActivatingId === item.id ? '切换中...' : item.isActive ? '当前版本' : '设为生效'}
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'backup' && (
            <div className="p-6 space-y-5">
              <div className="flex justify-between items-end gap-3">
                <div>
                  <h2 className="text-lg font-headline font-bold text-on-surface">备份与恢复</h2>
                  <p className="text-sm text-on-surface-variant mt-1">支持手动快照与一键恢复。</p>
                  {latestRestoreAt && <p className="text-xs text-outline mt-1">最近恢复时间：{latestRestoreAt}</p>}
                </div>
                <div className="flex gap-2">
                  <input
                    value={backupNote}
                    onChange={(event) => setBackupNote(event.target.value)}
                    placeholder="备份备注（可选）"
                    className="h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm w-56"
                  />
                  <button
                    onClick={handleCreateBackup}
                    disabled={backupCreating}
                    className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {backupCreating ? '创建中...' : '创建备份'}
                  </button>
                </div>
              </div>

              {!backups.length ? (
                <PageEmpty title="暂无备份记录" description="可先创建一次手动备份。" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-container-high">
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">备份 ID</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">类型</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">大小</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">创建信息</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">状态</th>
                        <th className="px-3 py-2 text-left text-xs text-on-surface-variant uppercase">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {backups.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/50">
                          <td className="px-3 py-3 font-mono text-xs">{item.id}</td>
                          <td className="px-3 py-3">{item.type === 'manual' ? '手动' : '自动'}</td>
                          <td className="px-3 py-3">{item.size}</td>
                          <td className="px-3 py-3 text-xs text-outline">{item.createdBy} · {item.createdAt}</td>
                          <td className="px-3 py-3">
                            <span className={`text-xs px-2 py-1 rounded ${
                              item.status === 'success'
                                ? 'bg-secondary-container text-on-secondary-container'
                                : 'bg-error-container text-on-error-container'
                            }`}>
                              {item.status === 'success' ? '可用' : '失败'}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            <button
                              onClick={() => handleRestoreBackup(item.id)}
                              disabled={backupRestoringId === item.id}
                              className="text-xs text-primary hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {backupRestoringId === item.id ? '恢复中...' : '恢复'}
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

          {activeSection === 'users' && (
            <div className="p-6 space-y-4">
              <div>
                <h2 className="text-lg font-headline font-bold text-on-surface">用户与角色</h2>
                <p className="text-sm text-on-surface-variant mt-1">当前保留基础用户视图，核心功能已聚焦系统模块治理。</p>
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
