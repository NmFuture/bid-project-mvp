import { useState } from 'react'
import { technicalGapsAPI, technicalMaterialsAPI } from '../../../api'
import {
  asObjectArray,
  backupMaterialEntries,
  fillBlankEntriesForTasks,
  isFillTemplateMaterial,
  moveListItem,
  recommendedSelectionsForItem,
  toggleListKey,
} from './technicalGapRecognitionHelpers'

// 素材选择/上传族 hook（从 TechnicalGapRecognition.jsx 第二轮拆分抽出）：
// 备选池派生模型（待填写空白、系统预选、备选条目）、多选铺开、限定库搜索、
// 选用（单个/多份）与「上传即选用」。
export const useMaterialSelection = ({
  projectId,
  items,
  selected,
  settledSelected,
  selectedFillTasks,
  selectedReferenceCandidates,
  selectedMaterialIdSet,
  runAction,
  showToast,
  scopePaths,
  materialScope,
  data,
  projectTurbineModel,
}) => {
  const [materialKeyword, setMaterialKeyword] = useState('')
  const [materialSearch, setMaterialSearch] = useState({ items: [], total: 0 })
  const [materialLoading, setMaterialLoading] = useState(false)
  // 定案项的备选区默认收起，「更换素材」临时展开；切换目录项时复位。
  const [materialSwapOpen, setMaterialSwapOpen] = useState(false)
  // 多机型等场景下一个目录项要串行铺开多份素材：按勾选顺序提交，顺序即正文顺序。
  const [multiPickOpen, setMultiPickOpen] = useState(false)
  const [multiPickKeys, setMultiPickKeys] = useState([])

  // 素材卡统一交互：待填写判定 = 命名纪律前缀，或该素材就是本目录项填写任务的空白模板
  //（兼容「待填写、待用印-」这类不合严格前缀的存量命名）。
  const fillTaskBlankMaterialIds = new Set(
    asObjectArray(selectedFillTasks)
      .map((task) => String(task?.blankSource?.materialId || task?.blankSource?.id || '').trim())
      .filter(Boolean),
  )
  const materialFillable = (material) => {
    const materialId = String(material?.id || material?.materialId || '').trim()
    return isFillTemplateMaterial(material) || (Boolean(materialId) && fillTaskBlankMaterialIds.has(materialId))
  }

  const fillBlankEntries = fillBlankEntriesForTasks(selectedFillTasks)
  // 解析空副表天然常驻已选区；素材类模板空白在「定案后」（待填写/待审核）也提升到已选区
  // ——否则定案项的备选池收起后，用户看不到定的是哪份模板（产品反馈 2026-08-04）。
  // 整章模板（chapter_fill）同一份素材会同时出现在 matchedMaterials 与 fillTask.blankSource：
  // matchedMaterials 卡（带分数/层级）已在已选区时，模板空白不再重复渲染（产品反馈 2026-08-04）。
  // planner 可能给出多份推荐（多机型时每个机型目录各一份），都要标成系统预选。
  const matchedMaterialIds = new Set(
    asObjectArray(selected?.matchedMaterials)
      .map((material) => String(material?.id || material?.materialId || '').trim())
      .filter(Boolean),
  )
  const topBlankEntries = fillBlankEntries.filter((entry) => {
    if (!entry.isMaterialBlank) return true
    if (!settledSelected) return false
    return !matchedMaterialIds.has(entry.key)
  })
  const poolBlankEntries = fillBlankEntries.filter((entry) => entry.isMaterialBlank && !settledSelected)
  const defaultSelections = recommendedSelectionsForItem(selected, items)
  const defaultSelection = defaultSelections[0] || null
  const selectedCardMaterialIds = new Set(
    defaultSelections
      .map((selection) => String(selection.material?.id || selection.material?.materialId || '').trim())
      .filter(Boolean),
  )
  // 备选素材 = 统一候选池剔除已选中项；解析空副表常驻已选区，不进备选池。
  const backupEntries = backupMaterialEntries({
    topBlankEntries,
    selectedCardMaterialIds,
    selectedMaterialIdSet,
    poolBlankEntries,
    referenceCandidates: selectedReferenceCandidates,
    matchedMaterialIds,
  })

  const multiPickMaterialOf = (key) => {
    const wrapper = backupEntries.find((item) => item.key === key)
    if (!wrapper) return null
    return wrapper.kind === 'blank' ? wrapper.entry.material : wrapper.material
  }
  const multiPickMaterialName = (key) => {
    const material = multiPickMaterialOf(key)
    return material?.name || material?.cleanedFileName || key
  }
  const toggleMultiPick = (key) => {
    setMultiPickKeys((prev) => toggleListKey(prev, key))
  }
  const moveMultiPick = (index, offset) => {
    setMultiPickKeys((prev) => moveListItem(prev, index, offset))
  }

  const handleSearchMaterials = async () => {
    setMaterialLoading(true)
    try {
      const targetPaths = scopePaths.length ? scopePaths : ['']
      const payloads = await Promise.all(targetPaths.map((folderPath) => technicalMaterialsAPI.raw.files({
        folderPath,
        keyword: materialKeyword,
        bidType: materialScope?.bidType || data?.bidType || '技术标',
        turbineModel: projectTurbineModel?.model || '',
        pageSize: 12,
        recursive: true,
      })))
      const seen = new Set()
      const searchItems = payloads.flatMap((payload) => (Array.isArray(payload?.items) ? payload.items : []))
        .filter((item) => {
          const key = item?.id || `${item?.folderPath || ''}/${item?.name || ''}`
          if (!key || seen.has(key)) return false
          seen.add(key)
          return true
        })
      setMaterialSearch({
        items: searchItems,
        total: searchItems.length,
      })
    } catch (e) {
      showToast?.(e?.message || '查询素材失败', 'error')
    } finally {
      setMaterialLoading(false)
    }
  }

  const handleSelectMaterial = async (material) => {
    const materialId = String(material?.id || material?.materialId || '').trim()
    if (!selected || !materialId) return null
    return runAction(
      `select-material:${selected.id}:${materialId}`,
      () => technicalGapsAPI.selectMaterial(projectId, selected.id, {
        materials: [{ ...material, id: materialId, materialId }],
        operator: '当前用户',
      }),
      (result) => result?.artifact?.fileName
        ? `已选用素材：${result.artifact.fileName}`
        : '已选用素材',
    )
  }

  // 一次提交多份：后端按数组顺序生成产物，顺序即正文里的铺开顺序。
  const handleSelectMaterials = async (materials) => {
    const payload = materials
      .map((material) => {
        const materialId = String(material?.id || material?.materialId || '').trim()
        return materialId ? { ...material, id: materialId, materialId } : null
      })
      .filter(Boolean)
    if (!selected || !payload.length) return null
    return runAction(
      `select-material:${selected.id}:multi`,
      () => technicalGapsAPI.selectMaterial(projectId, selected.id, {
        materials: payload,
        operator: '当前用户',
      }),
      () => `已按顺序选用 ${payload.length} 份素材`,
    )
  }

  // 多选提交：按勾选顺序铺开；成功后清空勾选并退出多选。
  const submitMultiPick = async () => {
    const materials = multiPickKeys.map(multiPickMaterialOf).filter(Boolean)
    const result = await handleSelectMaterials(materials)
    if (result) {
      setMultiPickKeys([])
      setMultiPickOpen(false)
    }
    return result
  }

  // 上传即选用：文件以 data URL 提交到 gaps/{gapId}/upload，后端存为人工产物
  //（source=manual_upload，s7Ready），终审直接判就绪。后端按 ZIP 魔数校验，仅支持 .docx。
  const handleUploadGapMaterial = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !selected) return null
    if (!file.name.toLowerCase().endsWith('.docx')) {
      showToast?.('目前仅支持上传 .docx 素材，其他格式请先转换后再上传', 'error')
      return null
    }
    let dataUrl = ''
    try {
      dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || ''))
        reader.onerror = () => reject(new Error('读取文件失败，请重试'))
        reader.readAsDataURL(file)
      })
    } catch (e) {
      showToast?.(e?.message || '读取文件失败，请重试', 'error')
      return null
    }
    if (!dataUrl) return null
    return runAction(
      `upload:${selected.id}`,
      () => technicalGapsAPI.upload(projectId, selected.id, {
        files: [{ name: file.name, data: dataUrl }],
        operator: '当前用户',
      }),
      (result) => (result?.artifact?.fileName
        ? `已上传并选用：${result.artifact.fileName}`
        : '已上传并选用素材'),
    )
  }

  // 切换目录项时复位素材区交互态（备选区收起、退出多选、清空勾选）。
  const resetMaterialPick = () => {
    setMaterialSwapOpen(false)
    setMultiPickOpen(false)
    setMultiPickKeys([])
  }

  return {
    materialKeyword,
    setMaterialKeyword,
    materialSearch,
    materialLoading,
    materialSwapOpen,
    setMaterialSwapOpen,
    multiPickOpen,
    setMultiPickOpen,
    multiPickKeys,
    setMultiPickKeys,
    materialFillable,
    matchedMaterialIds,
    topBlankEntries,
    defaultSelections,
    defaultSelection,
    backupEntries,
    multiPickMaterialOf,
    multiPickMaterialName,
    toggleMultiPick,
    moveMultiPick,
    submitMultiPick,
    handleSearchMaterials,
    handleSelectMaterial,
    handleSelectMaterials,
    handleUploadGapMaterial,
    resetMaterialPick,
  }
}
