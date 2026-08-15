import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import {
  isFillTemplateMaterial,
  materialTierLabels,
  technicalMatchScore,
} from './technicalGapRecognitionHelpers'

// 素材卡（产品裁决 2026-07-21 交互重构）：候选池/搜索结果里的素材一律只有 预览 + 选择；
// 点「选择」进入上方已选区后，待填写素材（命名纪律「待填写-」前缀或填写任务空白模板）
// 才出现 AI填写，不用填写的已选素材只有 预览——AI填写 按钮仅在传入 onAiFill 时渲染。
// leading 用于前置控件（如 AI 参考素材勾选框）。系统召回、来源推荐、搜索结果共用此卡片。
// coverageLabel：父级覆盖等场景的说明标签，只加标签不改变卡片基础结构（产品意见 2026-07-17）。
// onSelect 为空时不渲染「选择」按钮（如解析空表、AI 参考素材弹窗）；
// onCardClick 使整卡可点（AI 弹窗里点卡即勾选参考素材），卡内按钮均阻断冒泡。
function MaterialCandidateCard({
  material,
  isSelected,
  busy,
  selecting,
  onPreview,
  onSelect,
  fillable,
  onAiFill,
  aiFillBusy,
  aiFillCompleted,
  aiFillDisabled,
  aiFillDisabledReason,
  leading,
  coverageLabel,
  onCardClick,
}) {
  const name = material.name || material.cleanedFileName || material.id || material.materialId
  const path = material.folderPath || material.path || material.id
  // 新口径 matchScore 已是 0~1（启发式封顶 0.98，0.99=文件名精确命中）；Math.min 仅为存量旧版无界分兜底。
  const matchPercent = Math.min(100, Math.round(technicalMatchScore(material) * 100))
  const tierLabel = materialTierLabels[String(material.materialTier || '')] || ''
  const isFillable = fillable ?? isFillTemplateMaterial(material)
  // 展示极简口径（产品裁决）：文件名 + 匹配度 + 路径，不展示召回原因/清洗状态/证据片段。
  // 匹配度做成色块徽标（≥99 绿 = 精确命中 / ≥50 琥珀 / <50 灰 = 低置信），按钮横排收紧卡片高度。
  return (
    <div
      onClick={onCardClick || undefined}
      className={`rounded-lg border px-3 py-2.5 text-xs transition-[background-color,border-color,box-shadow,color] ${
        isSelected ? 'border-secondary bg-secondary-container/40' : 'border-surface-container-high bg-surface-container-lowest hover:border-primary/30 hover:shadow-sm'
      }${onCardClick ? ' cursor-pointer' : ''}`}
    >
      <div className="flex items-center justify-between gap-3">
        {leading || null}
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold text-on-surface" title={name}>{name}</span>
            {matchPercent > 0 ? (
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${
                  matchPercent >= 99
                    ? 'bg-secondary-container text-on-secondary-container'
                    : matchPercent >= 50
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-surface-container-high text-outline'
                }`}
              >
                {matchPercent}%{matchPercent < 50 ? ' 低置信' : ''}
              </span>
            ) : null}
            {isSelected ? <Badge size="xs" variant="done">已选中</Badge> : null}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5">
            {coverageLabel ? <Badge size="xs" variant="pending">{coverageLabel}</Badge> : null}
            {isFillable ? <Badge size="xs" variant="info">待填写</Badge> : null}
            {tierLabel ? <span className="shrink-0 text-[10px] text-outline">{tierLabel}</span> : null}
            <span className="min-w-0 truncate text-[11px] text-outline" title={path}>{path}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onPreview(material)
            }}
            disabled={busy}
            size="sm"
            variant="quiet"
          >
            预览
          </Button>
          {onSelect ? (
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onSelect(material)
              }}
              disabled={busy}
              size="sm"
              variant={isSelected ? 'secondary' : 'primary'}
            >
              {selecting ? '选择中...' : isSelected ? '已选中' : '选择'}
            </Button>
          ) : null}
          {isFillable && onAiFill ? (
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onAiFill(material)
              }}
              disabled={busy || aiFillDisabled}
              title={aiFillDisabled ? (aiFillDisabledReason || '') : aiFillCompleted ? '已完成，可再次发起 AI 填写' : ''}
              size="sm"
              variant="secondary"
            >
              {aiFillBusy ? 'AI填写中...' : aiFillCompleted ? (
                <>
                  <span className="material-symbols-outlined align-[-3px] text-[14px] text-secondary">check_circle</span>
                  已AI填写
                </>
              ) : 'AI填写'}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default MaterialCandidateCard
