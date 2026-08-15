import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import {
  asObjectArray,
  isStructuralItem,
  TECHNICAL_GAP_TAG_CONFIG,
  technicalGapDescendants,
  technicalGapFillError,
  technicalGapQualityFlag,
  technicalGapTagOf,
} from './technicalGapRecognitionHelpers'

// 目录列表里的标签：三字工作态 / 四字旁路态（命名 v6，产品裁决 2026-08-04），hover 出提示。
// 「仅留标题」的三条来源已在 technicalGapOwnTag 收口为同一个标签，这里只按来源区分 tip，
// 消除"第1章为什么没标签还放开了子级"的困惑（产品反馈 2026-08-04）。
export function TechnicalTocActionBadge({ item, items }) {
  const tag = technicalGapTagOf(item, items)
  const config = TECHNICAL_GAP_TAG_CONFIG[tag]
  if (!config) return null
  const tip = tag === 'title_only' && !item?.titleOnly
    ? '未找到整章素材，内容由下级承接'
    : config.tip
  return (
    <Badge className="business-toc-status-badge" shape="square" size="xs" variant={config.variant} title={tip}>
      {config.label}
    </Badge>
  )
}

// 逐条质量警示徽标（frontend-01）：AI 填写未过质检或仍有未填字段时亮黄标，hover 出原因。
// 与工作态标签并列但不抢口径：标签说「待审核」，徽标说「为什么值得警惕」。
export function TechnicalGapQualityBadge({ item }) {
  const flag = technicalGapQualityFlag(item)
  if (!flag) return null
  return (
    <span title={flag.tip}>
      <Badge shape="square" size="xs" variant="warn">{flag.label}</Badge>
    </span>
  )
}

// 详情区警示条：选中项有待复核质量问题时，在标题下方点明原因，
// 与列表行徽标、批量复核按钮 title 共用 technicalGapQualityFlag 同一口径。
export function TechnicalGapQualityNotice({ item }) {
  const flag = technicalGapQualityFlag(item)
  if (!flag) return null
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5 text-xs text-amber-800">
      <span className="material-symbols-outlined text-[15px]">warning</span>
      <span className="min-w-0">{flag.tip}</span>
    </div>
  )
}

// 右侧详情面板标题旁的操作控件（产品裁决 2026-08-04 v6）：
// - 「忽略/取消忽略」：有下级且未被冻结的节点都有——红色「待补充」的章、无标签骨架章同样适用；
//   列表行保持纯展示（回归 2026-07-21 裁决），忽略操作只在这里。
// - 「确认」：只对有系统预选素材（matchedMaterials 非空）的待确认项渲染——空确认不产生定案
//   （产品反馈 2026-08-04）；备选/搜索里的素材走「选择」即定案。
// - 已定案（待填写/已就绪）：展示定案态，可点撤销回落；
// - 待审核：「重新AI填写」+「复核通过」。
export function TechnicalGapActionControls({ item, items, busy, onConfirmReady, onReviewPass, onRefill, onTitleOnly }) {
  const tag = technicalGapTagOf(item, items)
  if (tag === 'parent_covered') return null
  const ignored = tag === 'title_only'
  // 结构章天生骨架，无自身匹配可忽略；忽略按钮只给「有自身匹配的带下级节点」。
  const hasChildren = !isStructuralItem(item) && technicalGapDescendants(item, items).length > 0
  const ignoreButton = hasChildren ? (
    <Button
      type="button"
      onClick={() => onTitleOnly(item, !ignored)}
      disabled={busy}
      title={ignored ? '取消忽略：本级恢复匹配素材，子级重新冻结' : '忽略本级：仅保留标题，下级各自匹配素材'}
      size="sm"
      variant="quiet"
    >
      {ignored ? '取消忽略' : '忽略本级'}
    </Button>
  ) : null
  if (ignored) return ignoreButton
  if (tag === 'template_review') {
    return (
      <>
        {ignoreButton}
        <Button
          type="button"
          onClick={() => onRefill(item)}
          disabled={busy}
          title="复核不通过时重新发起 AI 填写"
          size="sm"
          variant="secondary"
        >
          重新AI填写
        </Button>
        <Button
          type="button"
          onClick={() => onReviewPass(item)}
          disabled={busy}
          title="确认 AI 填写结果无误，本条定案"
          size="sm"
          variant="primary"
        >
          复核通过
        </Button>
      </>
    )
  }
  const settled = tag === 'material_ready' || tag === 'template_ready'
  const confirmable = tag === 'needs_choice' && asObjectArray(item?.matchedMaterials).length > 0
  // 上一轮填写失败的项停在「待填写」，这里给出原地重填入口（一键批量里失败的也走这条）
  const fillError = technicalGapFillError(item)
  return (
    <>
      {ignoreButton}
      {fillError ? (
        <Button
          type="button"
          onClick={() => onRefill(item)}
          disabled={busy}
          title={`上次填写失败：${fillError}`}
          size="sm"
          variant="secondary"
        >
          重新填写
        </Button>
      ) : null}
      {settled || confirmable ? (
        <Button
          type="button"
          onClick={() => onConfirmReady(item, !settled)}
          disabled={busy}
          title={settled ? '已定案，点击撤销（回落到待确认）' : '确认使用系统预选的素材'}
          size="sm"
          variant={settled ? 'secondary' : 'primary'}
        >
          {settled ? '已定案' : '确认'}
        </Button>
      ) : null}
    </>
  )
}
