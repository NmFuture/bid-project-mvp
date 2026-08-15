import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { technicalMaterialsAPI, technicalProjectsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import TechnicalFactSpecsEditModal from '../components/TechnicalFactSpecsEditModal'
import TechnicalAppendixRulesEditModal from '../components/TechnicalAppendixRulesEditModal'
import Button from '../../../components/ui/Button'
import { PageError, PageLoading } from '../../../components/states/PageState'
import { OTHER_OPTION_LABEL, deriveCustomerOptionsFromIndex } from '../../shared/projectInfoOptions'
import { technicalAppendixSourceMatrixUploadMessage } from './technicalGapRecognitionHelpers'

// 与各列表页一致的本地时间格式（zh-CN、24 小时制）
const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

const FACT_SPECS_SOURCE_LABELS = {
  override: '全局上传',
  none: '尚未上传',
}

const SELECT_CLASS =
  'h-9 w-full max-w-md cursor-pointer rounded-lg border border-outline-variant/80 bg-white px-3 text-sm text-on-surface transition-colors hover:border-outline focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-surface-container-low disabled:text-on-surface-variant'

function MetaRow({ label, children }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2 text-sm">
      <span className="shrink-0 text-on-surface-variant">{label}</span>
      <span className="min-w-0 truncate font-medium text-on-surface">{children}</span>
    </div>
  )
}

export default function TechnicalMaterialRules({ showToast = () => {} }) {
  const navigate = useNavigate()
  const [factSpecsMeta, setFactSpecsMeta] = useState(null)
  const [projects, setProjects] = useState([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [customerOptions, setCustomerOptions] = useState([])
  const [customerOptionsError, setCustomerOptionsError] = useState('')
  const [selectedCustomer, setSelectedCustomer] = useState('')
  const [matrixMeta, setMatrixMeta] = useState(null)
  const [matrixLoading, setMatrixLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [factSpecsEditOpen, setFactSpecsEditOpen] = useState(false)
  const [matrixEditOpen, setMatrixEditOpen] = useState(false)
  const factSpecsInputRef = useRef(null)
  const matrixInputRef = useRef(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    setCustomerOptionsError('')
    try {
      const [metaPayload, projectsPayload] = await Promise.all([
        technicalMaterialsAPI.rules.factSpecsMeta(),
        technicalProjectsAPI.list({ bidType: '技术标', reviewDecision: 'participate', page: 1, pageSize: 100 }),
      ])
      setFactSpecsMeta(metaPayload || null)
      const items = Array.isArray(projectsPayload?.items) ? projectsPayload.items : []
      setProjects(items)
      setSelectedProjectId((current) => (items.some((project) => project.id === current) ? current : items[0]?.id || ''))
    } catch (e) {
      setError(e?.message || '规则信息加载失败')
      setLoading(false)
      return
    }
    // 客户候选来自素材库三级目录索引（与建项目弹窗同源），失败只提示、不阻断页面其他区。
    try {
      const loadIndex = technicalMaterialsAPI.indexOptions || technicalMaterialsAPI.index
      const indexPayload = await loadIndex()
      const customers = deriveCustomerOptionsFromIndex(indexPayload).filter((name) => name !== OTHER_OPTION_LABEL)
      setCustomerOptions(customers)
      setSelectedCustomer((current) => (customers.includes(current) ? current : customers[0] || ''))
    } catch (e) {
      setCustomerOptions([])
      setSelectedCustomer('')
      setCustomerOptionsError(e?.message || '素材库客户清单加载失败，附表填写规则暂不可维护。')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  // 附表填写规则跟随客户：切换客户时拉取该客户的规则元数据，未维护按空态展示
  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      if (!selectedCustomer) {
        setMatrixMeta(null)
        return
      }
      setMatrixLoading(true)
      technicalMaterialsAPI.rules.appendixMatrixMeta(selectedCustomer)
        .then((payload) => {
          if (!cancelled) setMatrixMeta(payload || null)
        })
        .catch(() => {
          if (!cancelled) setMatrixMeta(null)
        })
        .finally(() => {
          if (!cancelled) setMatrixLoading(false)
        })
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [selectedCustomer])

  const refreshFactSpecsMeta = useCallback(async () => {
    try {
      const meta = await technicalMaterialsAPI.rules.factSpecsMeta()
      setFactSpecsMeta(meta || null)
    } catch {
      // 元数据刷新失败不打断主流程，下次进页或操作时再拉
    }
  }, [])

  const refreshMatrixMeta = useCallback(async () => {
    if (!selectedCustomer) return
    try {
      const meta = await technicalMaterialsAPI.rules.appendixMatrixMeta(selectedCustomer)
      setMatrixMeta(meta || null)
    } catch {
      // 同上：刷新失败静默，保留旧展示
    }
  }, [selectedCustomer])

  const handleFactSpecsUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.xlsx$/i.test(file.name)) {
      showToast('事实表清单仅支持 .xlsx 文件', 'error')
      return
    }
    if (busyAction) return
    if (
      factSpecsMeta?.source === 'override'
      && !window.confirm(`已有全局上传的事实表清单（${factSpecsMeta?.fileName || '已上传'}），重新上传将完整覆盖。是否继续？`)
    ) {
      return
    }
    setBusyAction('fact-specs-upload')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const payload = await technicalMaterialsAPI.rules.uploadFactSpecs(formData)
      const meta = await technicalMaterialsAPI.rules.factSpecsMeta()
      setFactSpecsMeta(meta || null)
      const specTotal = Number(payload?.specTotal ?? meta?.specTotal ?? 0)
      showToast(`已解析 ${specTotal} 个字段，全局事实表清单已生效，所有技术标项目共用`)
    } catch (e) {
      showToast(e?.message || '事实表清单上传失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const handleMatrixUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.xlsx$/i.test(file.name)) {
      showToast('附表填写规则仅支持 .xlsx 文件', 'error')
      return
    }
    if (busyAction || !selectedCustomer) return
    const hasExistingRules = Boolean(matrixMeta?.fileName) || Number(matrixMeta?.rowCount) > 0
    if (
      hasExistingRules
      && !window.confirm(`重新上传会以新文件完整覆盖「${selectedCustomer}」的附表填写规则；新文件未包含的旧规则及其推荐素材会被清除。是否继续？`)
    ) {
      return
    }
    setBusyAction('matrix-upload')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const payload = await technicalMaterialsAPI.rules.uploadAppendixMatrix(selectedCustomer, formData)
      const meta = await technicalMaterialsAPI.rules.appendixMatrixMeta(selectedCustomer)
      setMatrixMeta(meta || null)
      showToast(`${technicalAppendixSourceMatrixUploadMessage(payload)}，已同步到该客户名下项目的缺口识别`)
    } catch (e) {
      showToast(e?.message || '附表填写规则上传失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  if (loading) return <PageLoading title="正在加载规则维护..." />
  if (error) return <PageError title="规则维护加载失败" description={error} onRetry={loadData} />

  const factSpecsSource = String(factSpecsMeta?.source || '')
  // 下载原件只对全局上传的存档开放；系统默认清单没有上传存档（后端 404），按钮禁用
  const factSpecsDownloadable = factSpecsSource === 'override' && Boolean(factSpecsMeta?.fileName)
  const matrixImported = Boolean(matrixMeta?.fileName) || Number(matrixMeta?.rowCount) > 0
  const matrixUpdatedAt = matrixMeta?.uploadedAt || matrixMeta?.updatedAt
  const selectedProject = projects.find((project) => project.id === selectedProjectId) || null
  // 目录确认后后端会把项目阶段顶到 >=3（素材匹配及以后），未确认目录的项目不允许进入素材匹配（R11-B07-03）
  const selectedProjectOutlineReady = Number(selectedProject?.currentStage) >= 3

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <MaterialsViewSwitch
        active="rules"
        title="技术标规则"
      />

      <section className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-4 lg:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-headline font-semibold text-on-surface">项目事实表清单（全局生效）</h2>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
            <input
              ref={factSpecsInputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={handleFactSpecsUpload}
            />
            <Button
              type="button"
              onClick={() => factSpecsInputRef.current?.click()}
              disabled={Boolean(busyAction)}
              size="sm"
              variant="primary"
            >
              {busyAction === 'fact-specs-upload' ? '上传中...' : factSpecsDownloadable ? '重新上传' : '上传清单'}
            </Button>
            <Button
              type="button"
              onClick={() => window.open(technicalMaterialsAPI.rules.factSpecsDownloadUrl(), '_blank', 'noopener')}
              disabled={!factSpecsDownloadable || Boolean(busyAction)}
              title={factSpecsDownloadable ? `下载 ${factSpecsMeta?.fileName}` : '系统默认清单没有上传存档可下载'}
              size="sm"
              variant="quiet"
            >
              下载原件
            </Button>
            <Button
              type="button"
              onClick={() => window.open(technicalMaterialsAPI.rules.factSpecsExportUrl(), '_blank', 'noopener')}
              disabled={Boolean(busyAction)}
              title="按当前生效清单生成 Excel"
              size="sm"
              variant="quiet"
            >
              导出 Excel
            </Button>
            <Button
              type="button"
              onClick={() => setFactSpecsEditOpen(true)}
              disabled={Boolean(busyAction)}
              size="sm"
              variant="quiet"
            >
              在线编辑
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-1.5">
          <MetaRow label="生效来源">{FACT_SPECS_SOURCE_LABELS[factSpecsSource] || factSpecsSource || '-'}</MetaRow>
          <MetaRow label="文件名">{factSpecsMeta?.fileName || '-'}</MetaRow>
          <MetaRow label="上传时间">{factSpecsMeta?.uploadedAt ? formatDateTime(factSpecsMeta.uploadedAt) : '-'}</MetaRow>
          <MetaRow label="字段总数">{Number.isFinite(Number(factSpecsMeta?.specTotal)) ? Number(factSpecsMeta?.specTotal) : '-'}</MetaRow>
        </div>
      </section>

      <section className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-4 lg:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-headline font-semibold text-on-surface">附表填写规则（按客户）</h2>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
            <input
              ref={matrixInputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={handleMatrixUpload}
            />
            <Button
              type="button"
              onClick={() => matrixInputRef.current?.click()}
              disabled={!selectedCustomer || Boolean(busyAction)}
              size="sm"
              variant="primary"
            >
              {busyAction === 'matrix-upload' ? '上传中...' : matrixImported ? '重新上传' : '上传 Excel'}
            </Button>
            <Button
              type="button"
              onClick={() => window.open(technicalMaterialsAPI.rules.appendixMatrixExportUrl(selectedCustomer), '_blank', 'noopener')}
              disabled={!selectedCustomer || !matrixImported || Boolean(busyAction)}
              title={matrixImported ? `导出「${selectedCustomer}」的规则为 Excel` : '该客户尚未维护附表填写规则'}
              size="sm"
              variant="quiet"
            >
              导出 Excel
            </Button>
            <Button
              type="button"
              onClick={() => setMatrixEditOpen(true)}
              disabled={!selectedCustomer || Boolean(busyAction)}
              size="sm"
              variant="quiet"
            >
              在线编辑
            </Button>
          </div>
        </div>
        <div className="mt-3">
          <select
            value={selectedCustomer}
            onChange={(event) => setSelectedCustomer(event.target.value)}
            disabled={!customerOptions.length || Boolean(busyAction)}
            className={SELECT_CLASS}
            aria-label="选择客户"
          >
            {customerOptions.length ? null : <option value="">暂无素材库客户</option>}
            {customerOptions.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          {customerOptionsError ? (
            <p className="mt-1.5 text-xs text-error">{customerOptionsError}</p>
          ) : null}
        </div>
        {selectedCustomer ? (
          <div className="mt-3 flex flex-col gap-1.5">
            {matrixLoading ? (
              <p className="text-sm text-outline">正在加载该客户的规则信息...</p>
            ) : matrixImported ? (
              <>
                <MetaRow label="规则行数">{Number.isFinite(Number(matrixMeta?.rowCount)) ? Number(matrixMeta?.rowCount) : '-'}</MetaRow>
                <MetaRow label="文件名">{matrixMeta?.fileName || '-'}</MetaRow>
                <MetaRow label="上传时间">{matrixUpdatedAt ? formatDateTime(matrixUpdatedAt) : '-'}</MetaRow>
              </>
            ) : (
              <p className="text-sm text-outline">该客户未维护规则，其名下项目按无规则处理。</p>
            )}
          </div>
        ) : (
          <p className="mt-3 text-sm text-outline">暂无素材库客户，请先在素材库维护客户目录后再维护附表填写规则。</p>
        )}
      </section>

      <section className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-4 lg:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-headline font-semibold text-on-surface">项目工作区入口</h2>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
            <select
              value={selectedProjectId}
              onChange={(event) => setSelectedProjectId(event.target.value)}
              disabled={!projects.length}
              className={SELECT_CLASS}
              aria-label="选择要进入的项目"
            >
              {projects.length ? null : <option value="">暂无技术标项目</option>}
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name || project.id}</option>
              ))}
            </select>
            {selectedProjectId ? (
              <span
                className="inline-flex h-9 items-center rounded-lg border border-outline-variant/60 bg-surface-container-low px-2.5 font-mono text-xs font-semibold text-on-surface-variant"
                title="项目编号"
              >
                {selectedProjectId}
              </span>
            ) : null}
            <Button
              type="button"
              onClick={() => navigate(`/workspace/tech/projects/${selectedProjectId}/gaps`)}
              disabled={!selectedProjectId || !selectedProjectOutlineReady}
              title={
                !selectedProject
                  ? '进入项目工作区'
                  : !selectedProjectOutlineReady
                    ? '该项目尚未生成并确认投标目录，请先完成目录生成与确认'
                    : `进入「${selectedProject.name || selectedProject.id}」的素材匹配页`
              }
              size="sm"
              variant="primary"
            >
              进入
            </Button>
          </div>
        </div>
        {selectedProject && !selectedProjectOutlineReady ? (
          <p className="mt-2 text-xs text-amber-600">
            该项目尚未生成并确认投标目录，暂不能进入素材匹配；请先在项目中生成并确认目录。
          </p>
        ) : null}
      </section>

      {factSpecsEditOpen ? (
        <TechnicalFactSpecsEditModal
          onClose={() => setFactSpecsEditOpen(false)}
          onSaved={refreshFactSpecsMeta}
          showToast={showToast}
        />
      ) : null}
      {matrixEditOpen && selectedCustomer ? (
        <TechnicalAppendixRulesEditModal
          customerName={selectedCustomer}
          onClose={() => setMatrixEditOpen(false)}
          onSaved={refreshMatrixMeta}
          showToast={showToast}
        />
      ) : null}
    </div>
  )
}
