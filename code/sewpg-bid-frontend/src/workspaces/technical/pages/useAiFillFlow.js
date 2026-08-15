import { useState } from 'react'
import { technicalGapsAPI, technicalMaterialsAPI } from '../../../api'
import {
  TECHNICAL_WORD_FILL_SKILL,
  aiFillReferenceCandidatesForItem,
  aiFillSelectionKey,
  asObjectArray,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  mergeUploadedCandidates,
  resolveAiFillReferenceIds,
  toggleAiFillReferenceId,
  uniqueStrings,
} from './technicalGapRecognitionHelpers'

// AI 填写流 hook（从 TechnicalGapRecognition.jsx 第二轮拆分抽出）：
// 参考素材选择弹窗状态（当前任务/勾选态/手动上传的补充素材）、统一候选池派生、
// 单条 AI 填写执行（含事实表就绪守卫与填写完成后的预览跳转）、弹窗内补料上传。
export const useAiFillFlow = ({
  projectId,
  selected,
  selectedFillTask,
  activeAppendixTasks,
  selectedSourceRouting,
  selectedMaterialMatch,
  selectedCandidateMaterials,
  bodyFillRunning,
  factConfirmed,
  ensureFactTableReady,
  runAction,
  aiFillActionKey,
  busyAction,
  tagFilter,
  setTagFilter,
  setSelectedId,
  resetPreviewChoice,
  setPreviewChoiceKey,
  setPreviewOpen,
  readableScopes,
  materialScope,
  showToast,
}) => {
  const [aiFillReferenceSelections, setAiFillReferenceSelections] = useState({})
  // AI 填写弹窗：点素材卡上的 AI填写 打开，选参考素材后执行；null=关闭。
  const [aiFillModalTask, setAiFillModalTask] = useState(null)
  // AI 填写弹窗内手动上传的补充素材：入项目素材库后注入候选列表并默认勾选，
  // 关闭弹窗时清空，避免串到下一个附表任务。
  const [aiFillUploadedCandidates, setAiFillUploadedCandidates] = useState([])
  const [aiFillUploadBusy, setAiFillUploadBusy] = useState(false)

  const selectedReferenceCandidates = aiFillReferenceCandidatesForItem({
    tasks: activeAppendixTasks,
    item: selected,
    sourceRouting: selectedSourceRouting,
    materialMatch: selectedMaterialMatch,
    candidateMaterials: selectedCandidateMaterials,
    uploadedCandidates: aiFillUploadedCandidates,
  })

  // AI 填写参考素材勾选态按「目录项 × 填写任务」隔离；没勾选过时用该任务的推荐默认值。
  const aiFillSelectionKeyFor = (task) => aiFillSelectionKey(selected, task)
  const aiFillReferenceIdsFor = (task) => resolveAiFillReferenceIds(
    aiFillReferenceSelections,
    aiFillSelectionKeyFor(task),
    defaultAiFillReferenceMaterialIds(selected, [], task),
  )

  // task 缺省为首个填写任务；多空表目录项（如 附表F.5 双任务）由各自素材卡传入对应任务。
  const handleAiFill = async (task = selectedFillTask) => {
    if (!selected || !task) return null
    if (bodyFillRunning) {
      showToast?.('一键填写进行中，暂不可单条填写', 'error')
      return null
    }
    if (!factConfirmed && !(await ensureFactTableReady())) {
      return null
    }
    const referenceIds = aiFillReferenceIdsFor(task)
    const referenceMaterials = selectedReferenceCandidates.filter((material) => (
      referenceIds.includes(String(material?.id || material?.materialId || '').trim())
    ))
    const payload = await runAction(
      aiFillActionKey,
      () => technicalGapsAPI.aiFill(projectId, selected.id, {
        fillTaskId: task.id,
        referenceMaterialIds: referenceIds,
        referenceMaterials,
        parseFieldIds: defaultAiFillParseFieldIds(selected, task),
        operator: '当前用户',
      }),
      (result) => (result?.artifact?.fileName ? `AI填写完成：${result.artifact.fileName}` : 'AI填写完成'),
    )
    if (payload) {
      resetPreviewChoice()
      // 产品裁决 2026-08-04（行为①，推翻 2026-07-17 自动确认）：AI 填写完成后停在
      // 「待复核模板」，由人点「复核通过」定案；这里只弹出结果预览方便当场检查。
      const artifactId = String(payload?.artifact?.id || '').trim()
      if (artifactId) {
        // 填完这条就从「待填写」转入「待审核」。当前筛选容不下它时要跟着切过去并保持选中，
        // 否则它被挤出列表、选中项顺延到别的目录项，弹出的就不是刚填这条的对比了。
        const filledId = String(payload?.item?.id || selected?.id || '').trim()
        if (tagFilter && tagFilter !== 'template_review') setTagFilter('template_review')
        if (filledId) setSelectedId(filledId)
        setPreviewChoiceKey(`artifact:${artifactId}`)
        setPreviewOpen(true)
      }
    }
    return payload
  }

  // AI 填写入口：正文按事实表清单精确定位字段（占位符原文 → 字段），参考素材既不参与
  // 定位也不提供取值，点了直接跑；附表仍要先选参考素材，保持原有弹窗。
  const startAiFill = (task) => {
    if (!task) return
    // 一键填写进行中禁止单条填写（后端同样返回 409，这里提前拦截并提示原因）
    if (bodyFillRunning) {
      showToast?.('一键填写进行中，暂不可单条填写', 'error')
      return
    }
    if (String(task?.skill || '') === TECHNICAL_WORD_FILL_SKILL) {
      handleAiFill(task)
      return
    }
    setAiFillModalTask(task)
  }

  // 「重新AI填写」：复核不通过时原地重填（同任务产物替换）。
  const handleRefillAiFill = (item) => {
    const task = asObjectArray(item?.fillTasks)[0] || null
    if (task) startAiFill(task)
  }

  const handleToggleAiFillReference = (task, materialId) => {
    const key = aiFillSelectionKeyFor(task)
    if (!key || !materialId || busyAction) return
    const fallback = defaultAiFillReferenceMaterialIds(selected, [], task)
    setAiFillReferenceSelections((current) => {
      const active = Object.prototype.hasOwnProperty.call(current, key) ? current[key] : fallback
      return { ...current, [key]: toggleAiFillReferenceId(active, materialId) }
    })
  }

  // AI 填写弹窗内的补料上传：走素材库 raw upload 入「项目素材」目录（区别于目录项底部
  // 上传即定案的 gaps/{gid}/upload），拿到真实素材 id 后注入弹窗候选列表并默认勾选，
  // AI 填写链路（referenceMaterials）零改动——后端按 material_id 从 MinIO 下载，
  // 清洗未完成的素材回退原件也能用于填写。
  const handleAiFillUpload = async (files) => {
    const task = aiFillModalTask
    const fileList = Array.from(files || [])
    if (!task || !fileList.length) return
    const projectScope = readableScopes.find((scope) => String(scope?.key || '') === 'project')
    const targetPath = String(projectScope?.path || '').trim()
    if (!targetPath) {
      showToast?.('未找到项目素材目录，无法上传', 'error')
      return
    }
    const identity = materialScope?.identity || {}
    const buildForm = (onConflict) => {
      const form = new FormData()
      form.append('targetPath', targetPath)
      form.append('projectId', projectId)
      form.append('projectCode', String(identity.projectCode || ''))
      form.append('projectName', String(identity.projectName || ''))
      form.append('bidType', materialScope?.bidType || '技术标')
      form.append('materialTier', '')
      form.append('businessMaterialKind', 'other')
      form.append('customerId', '')
      form.append('customerName', '')
      if (onConflict) form.append('onConflict', onConflict)
      fileList.forEach((file) => {
        form.append('files', file, file.name)
        form.append('relativePaths', '')
      })
      return form
    }
    setAiFillUploadBusy(true)
    try {
      let result
      try {
        result = await technicalMaterialsAPI.raw.upload(buildForm(''))
      } catch (e) {
        // 同名冲突：归档旧版本后覆盖重试一次（对齐素材库页的 onConflict 语义）
        if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
          result = await technicalMaterialsAPI.raw.upload(buildForm('replace'))
        } else {
          throw e
        }
      }
      const items = asObjectArray(result?.items)
      if (!items.length) {
        showToast?.('上传完成，但未拿到素材记录，请到素材库确认', 'error')
        return
      }
      setAiFillUploadedCandidates((current) => mergeUploadedCandidates(current, items))
      const key = aiFillSelectionKeyFor(task)
      const uploadedIds = items.map((item) => String(item?.id || item?.materialId || '').trim()).filter(Boolean)
      if (key && uploadedIds.length) {
        setAiFillReferenceSelections((current) => {
          const active = Object.prototype.hasOwnProperty.call(current, key)
            ? current[key]
            : defaultAiFillReferenceMaterialIds(selected, [], task)
          return { ...current, [key]: uniqueStrings([...active, ...uploadedIds]) }
        })
      }
      showToast?.(`已上传 ${items.length} 份素材并加入本次 AI 填写参考`)
    } catch (e) {
      showToast?.(e?.message || '上传失败，请稍后重试', 'error')
    } finally {
      setAiFillUploadBusy(false)
    }
  }

  // 关闭弹窗（取消或确认前）：清空任务与手动上传的补充素材，避免串到下一个附表任务。
  const closeAiFillModal = () => {
    setAiFillModalTask(null)
    setAiFillUploadedCandidates([])
  }

  return {
    aiFillReferenceSelections,
    aiFillModalTask,
    aiFillUploadedCandidates,
    aiFillUploadBusy,
    selectedReferenceCandidates,
    aiFillSelectionKeyFor,
    aiFillReferenceIdsFor,
    handleAiFill,
    startAiFill,
    handleRefillAiFill,
    handleToggleAiFillReference,
    handleAiFillUpload,
    closeAiFillModal,
  }
}
