import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { technicalMaterialsAPI, technicalProjectsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import Button from '../../../components/ui/Button'
import { PageError, PageLoading } from '../../../components/states/PageState'
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
  'repo-default': '系统默认',
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
  const [matrixMeta, setMatrixMeta] = useState(null)
  const [matrixLoading, setMatrixLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const factSpecsInputRef = useRef(null)
  const matrixInputRef = useRef(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
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

  // 附表填写规则跟随项目：切换项目时拉取该项目的规则元数据，未上传按空态展示
  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      if (!selectedProjectId) {
        setMatrixMeta(null)
        return
      }
      setMatrixLoading(true)
      technicalMaterialsAPI.rules.appendixMatrixMeta(selectedProjectId)
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
  }, [selectedProjectId])

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
      showToast(`已解析 ${specTotal} 个字段，已生效，未绑定专属规则的项目将使用新清单`)
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
    if (busyAction || !selectedProjectId) return
    if (
      matrixMeta?.path
      && !window.confirm('重新上传会以新文件完整覆盖当前附表填写规则；新文件未包含的旧规则及其推荐素材会被清除。是否继续？')
    ) {
      return
    }
    setBusyAction('matrix-upload')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const payload = await technicalMaterialsAPI.rules.uploadAppendixMatrix(selectedProjectId, formData)
      const meta = await technicalMaterialsAPI.rules.appendixMatrixMeta(selectedProjectId)
      setMatrixMeta(meta || null)
      showToast(`${technicalAppendixSourceMatrixUploadMessage(payload)}，已同步到该项目的缺口识别`)
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
  const matrixImported = Boolean(matrixMeta?.path || matrixMeta?.fileName)
  const selectedProject = projects.find((project) => project.id === selectedProjectId) || null

  return (
    <div className="flex flex-col gap-3 animate-fade-in">
      <MaterialsViewSwitch
        active="rules"
        title="技术标素材库"
        subtitle="事实表清单与附表填写规则维护"
      />

      <section className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-4 lg:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-headline font-bold text-on-surface">项目事实表清单（全局生效）</h2>
            <p className="mt-1 text-xs text-outline">全平台只维护一份；未绑定专属规则的项目缺口识别时使用这份清单提取事实表字段。</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
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
              icon="upload_file"
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
              icon="download"
              size="sm"
              variant="quiet"
            >
              下载原件
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
            <h2 className="text-sm font-headline font-bold text-on-surface">附表填写规则（按项目）</h2>
            <p className="mt-1 text-xs text-outline">客户×附表→素材来源，缺口识别时确定每张附表的取值来源；按项目分别维护。</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
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
              disabled={!selectedProjectId || Boolean(busyAction)}
              icon="upload_file"
              size="sm"
              variant="primary"
            >
              {busyAction === 'matrix-upload' ? '上传中...' : matrixImported ? '重新上传' : '上传规则'}
            </Button>
            <Button
              type="button"
              onClick={() => window.open(technicalMaterialsAPI.rules.appendixMatrixDownloadUrl(selectedProjectId), '_blank', 'noopener')}
              disabled={!matrixImported || Boolean(busyAction)}
              title={matrixImported ? `下载 ${matrixMeta?.fileName}` : '该项目尚未上传附表填写规则'}
              icon="download"
              size="sm"
              variant="quiet"
            >
              下载原件
            </Button>
          </div>
        </div>
        <div className="mt-3">
          <select
            value={selectedProjectId}
            onChange={(event) => setSelectedProjectId(event.target.value)}
            disabled={!projects.length || Boolean(busyAction)}
            className={SELECT_CLASS}
            aria-label="选择项目"
          >
            {projects.length ? null : <option value="">暂无技术标项目</option>}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name || project.id}</option>
            ))}
          </select>
        </div>
        {selectedProjectId ? (
          <div className="mt-3 flex flex-col gap-1.5">
            {matrixLoading ? (
              <p className="text-sm text-outline">正在加载该项目的规则信息...</p>
            ) : matrixImported ? (
              <>
                <MetaRow label="文件名">{matrixMeta?.fileName || '-'}</MetaRow>
                <MetaRow label="规则行数">{Number.isFinite(Number(matrixMeta?.rowCount)) ? Number(matrixMeta?.rowCount) : '-'}</MetaRow>
                <MetaRow label="上传时间">{matrixMeta?.uploadedAt ? formatDateTime(matrixMeta.uploadedAt) : '-'}</MetaRow>
              </>
            ) : (
              <p className="text-sm text-outline">未上传</p>
            )}
          </div>
        ) : (
          <p className="mt-3 text-sm text-outline">暂无技术标项目，请先创建项目后再维护附表填写规则。</p>
        )}
      </section>

      <section className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest p-4 lg:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-headline font-bold text-on-surface">项目工作区入口</h2>
            <p className="mt-1 text-xs text-outline">维护完规则后直接进入所选项目的素材匹配页，无需返回项目列表查找。</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
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
              disabled={!selectedProjectId}
              title={selectedProject ? `进入「${selectedProject.name || selectedProject.id}」的素材匹配页` : '进入项目工作区'}
              icon="arrow_forward"
              size="sm"
              variant="primary"
            >
              进入
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}
