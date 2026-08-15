import { useCallback, useState } from 'react'
import { technicalGapsAPI } from '../../../api'
import { asObjectArray } from './technicalGapRecognitionHelpers'
import {
  applyFactFieldChange,
  createManualFactField,
  factFieldsToSave,
  hasUnnamedManualFactValue,
} from './technicalGapFactTable'
import { useBackgroundTaskPolling } from './useBackgroundTaskPolling'

// 事实表维护族 hook（从 TechnicalGapRecognition.jsx 第二轮拆分抽出）：
// 事实表状态（表/字段/清单元数据/参考范围/附表规则元数据）、字段编辑与保存定稿、
// 参考范围保存、AI 匹配填充提交与后台轮询恢复。
// 后台任务终态口径：AI 匹配填充只有成功/失败；轮询的去重与通知逻辑见
// useBackgroundTaskPolling / technicalGapTaskPolling。
const FACT_CURATE_TERMINAL_STATUSES = ['succeeded', 'failed']
const factCurateStateOf = (payload) => payload?.factCurateState || null

export const useFactTableMaintenance = ({
  projectId,
  setData,
  busyAction,
  setBusyAction,
  showToast,
  navigate,
}) => {
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])
  const [factCurateReport, setFactCurateReport] = useState(null)
  // 事实表清单与附表填写规则的上传维护已迁至素材库 · 规则页（/workspace/tech/materials/rules），
  // 本页只读 facts() 返回的元数据做状态展示；factMaterialPaths 是用户自定义的参考资料目录。
  const [factSpecsMeta, setFactSpecsMeta] = useState({ imported: false, fileName: '' })
  const [sourceMatrixMeta, setSourceMatrixMeta] = useState({ imported: false, fileName: '' })
  const [factMaterialPaths, setFactMaterialPaths] = useState([])
  // 默认生效的素材范围（标准文件/客户定制/项目定制三层），由后端按项目身份给出
  const [factMaterialScopes, setFactMaterialScopes] = useState([])
  // AI 匹配填充任务状态：执行在后台 worker，弹窗关闭/页面刷新都不影响，靠轮询恢复
  const [factCurateState, setFactCurateState] = useState(null)
  const factCurateRunning = ['queued', 'running'].includes(String(factCurateState?.status || ''))
  const factConfirmed = factTable?.status === 'confirmed'

  const ensureFactTableReady = async () => {
    if (factTable?.status === 'confirmed') return true
    // 清单全局唯一且尚未上传时不出字段：维护入口在素材库 · 规则页，引导跳转
    if (!factSpecsMeta.imported && !factFields.length) {
      if (window.confirm('尚未上传事实表清单，系统无法提取要填写的字段。是否前往素材库 · 规则页上传？')) {
        navigate('/workspace/tech/materials/rules')
      }
      return false
    }
    if (busyAction) return false

    setBusyAction('facts-auto')
    try {
      const currentFields = factFields.length
        ? factFields
        : asObjectArray((await technicalGapsAPI.buildFacts(projectId))?.fields)
      const fieldsToSave = factFieldsToSave(currentFields)
      const payload = await technicalGapsAPI.saveFacts(projectId, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      return true
    } catch (e) {
      showToast?.(e?.message || '内部项目数据准备失败，请稍后重试', 'error')
      return false
    } finally {
      setBusyAction('')
    }
  }

  const handleFactFieldChange = (index, key, value) => {
    setFactFields((current) => applyFactFieldChange(current, index, key, value))
  }

  const handleAddFactField = () => {
    setFactFields((current) => [
      ...current,
      createManualFactField({ id: `FACT-MANUAL-${Date.now()}`, createdAt: new Date().toISOString() }),
    ])
  }

  const handleConfirmFactTable = async () => {
    if (busyAction || !factFields.length) return null
    if (hasUnnamedManualFactValue(factFields)) {
      showToast?.('请先填写人工新增字段的字段名称', 'error')
      return null
    }
    const fieldsToSave = factFieldsToSave(factFields)
    setBusyAction('facts-confirm')
    try {
      const payload = await technicalGapsAPI.saveFacts(projectId, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      showToast?.('项目事实表已保存并定稿，正文填写将使用这一版')
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表保存失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const handleSaveMaterialPaths = async (paths) => {
    if (busyAction) return false
    setBusyAction('facts-material-sources')
    let pathsSaved = false
    try {
      const payload = await technicalGapsAPI.saveMaterialSources(projectId, { paths })
      setFactMaterialPaths(Array.isArray(payload?.paths) ? payload.paths : [])
      pathsSaved = true
      const table = await technicalGapsAPI.buildFacts(projectId)
      setFactTable(table)
      setFactFields(asObjectArray(table?.fields))
      setFactCurateReport(null)
      setData((current) => (current ? { ...current, projectFactTable: table } : current))
      showToast?.('参考范围已保存，事实表已自动更新')
      return true
    } catch (e) {
      showToast?.(
        pathsSaved
          ? `参考范围已保存，但事实表自动更新失败：${e?.message || '请重试保存范围'}`
          : (e?.message || '参考范围保存失败'),
        'error',
      )
      return false
    } finally {
      setBusyAction('')
    }
  }

  // 刷新并 AI 填充：保存当前编辑 → 按最新素材范围刷新事实表 → 事实表维护 Skill 按素材
  // 给字段补值/修正/口径建议，结果落为待人工确认
  const handleCurateFacts = async () => {
    if (busyAction) return
    if (hasUnnamedManualFactValue(factFields)) {
      showToast?.('请先填写人工新增字段的字段名称', 'error')
      return
    }
    setBusyAction('facts-curate')
    try {
      const fieldsToSave = factFieldsToSave(factFields)
      const savedTable = await technicalGapsAPI.saveFacts(projectId, {
        fields: fieldsToSave,
        confirm: false,
        operator: '当前用户',
      })
      setFactTable(savedTable)
      setFactFields(asObjectArray(savedTable?.fields))
      setData((current) => (current ? { ...current, projectFactTable: savedTable } : current))
      // 先按最新素材范围刷新事实表（重跑规则抽取，并把无值的终态字段复位为未提取），
      // 再交给 AI 补抽——否则上一轮标成「缺少来源」的字段不会进 AI 的工作清单。
      const rebuiltTable = await technicalGapsAPI.buildFacts(projectId)
      setFactTable(rebuiltTable)
      setFactFields(asObjectArray(rebuiltTable?.fields))
      setData((current) => (current ? { ...current, projectFactTable: rebuiltTable } : current))
      // 提交后台任务后立即返回，执行进度由轮询接管；此后关弹窗、刷新页面都不影响
      const payload = await technicalGapsAPI.curateFacts(projectId, {})
      setFactCurateReport(null)
      setFactCurateState(payload?.factCurateState || null)
      showToast?.(payload?.message || '已提交 AI 匹配填充任务')
    } catch (e) {
      showToast?.(e?.message || '匹配填充失败，请稍后重试', 'error')
    } finally {
      setBusyAction('')
    }
  }

  // AI 匹配填充轮询：任务在后台 worker 执行，这里只负责取进度；终态时把结果一次性落到界面。
  // 完成通知按 jobId+finishedAt 去重，避免收尾那一拍重复弹 toast。
  const fetchFactCurateStatus = useCallback(() => technicalGapsAPI.curateFactsStatus(projectId), [projectId])
  const handleFactCurateTerminal = useCallback(async (payload, state) => {
    const status = String(state?.status || '')
    if (payload?.projectFactTable?.schemaVersion) {
      setFactTable(payload.projectFactTable)
      setFactFields(asObjectArray(payload.projectFactTable.fields))
      setData((current) =>
        current ? { ...current, projectFactTable: payload.projectFactTable } : current,
      )
    }
    setFactCurateReport(payload?.curateReport || null)
    showToast?.(
      payload?.message || (status === 'succeeded' ? '匹配填充完成' : '匹配填充失败'),
      status === 'succeeded' ? undefined : 'error',
    )
  }, [setData, showToast])
  useBackgroundTaskPolling({
    running: factCurateRunning,
    fetchStatus: fetchFactCurateStatus,
    extractState: factCurateStateOf,
    terminalStatuses: FACT_CURATE_TERMINAL_STATUSES,
    onState: setFactCurateState,
    onTerminal: handleFactCurateTerminal,
  })

  return {
    factModalOpen,
    setFactModalOpen,
    factTable,
    setFactTable,
    factFields,
    setFactFields,
    factCurateReport,
    setFactCurateReport,
    factSpecsMeta,
    setFactSpecsMeta,
    sourceMatrixMeta,
    setSourceMatrixMeta,
    factMaterialPaths,
    setFactMaterialPaths,
    factMaterialScopes,
    setFactMaterialScopes,
    factCurateState,
    setFactCurateState,
    factCurateRunning,
    factConfirmed,
    ensureFactTableReady,
    handleFactFieldChange,
    handleAddFactField,
    handleConfirmFactTable,
    handleSaveMaterialPaths,
    handleCurateFacts,
  }
}
