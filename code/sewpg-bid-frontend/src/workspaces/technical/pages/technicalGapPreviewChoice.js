import { aiFillComparisonPair } from './technicalGapRecognitionHelpers.js'

// 预览族派生态（从 TechnicalGapRecognition.jsx 抽出），不依赖 React，可用 node --test 直接验证。

// 手工构造的预览项（预览某个空表/素材时现拼的 choice）只在它属于当前选中目录项、
// 且就是当前预览 key 时生效，否则回落到目录项自带的预览选项列表。
export const resolveGapPreviewChoice = ({
  choices,
  manualPreviewChoice,
  selectedId,
  previewChoiceKey,
}) => {
  const manualActive = manualPreviewChoice
    && manualPreviewChoice.itemId === selectedId
    && manualPreviewChoice.key === previewChoiceKey
    ? manualPreviewChoice
    : null
  const effectiveKey = manualActive
    ? manualActive.key
    : choices.some((choice) => choice.key === previewChoiceKey)
      ? previewChoiceKey
      : (choices[0]?.key || '')
  const selected = manualActive
    || choices.find((choice) => choice.key === effectiveKey)
    || null
  const visible = [...choices]
  if (manualActive && !visible.some((choice) => choice.key === manualActive.key)) {
    visible.push(manualActive)
  }
  return {
    manualActive,
    effectiveKey,
    selected,
    visible,
    comparison: aiFillComparisonPair(visible, selected),
  }
}

// 预览 session 防重载判定（历史坑：读 ref 避免重载）——同一产物同一版本
//（静默轮询带来的对象刷新）不重载编辑器，避免打断正在进行的在线编辑。
export const isSameArtifactPreviewSession = (choice, current) => Boolean(
  choice?.kind === 'artifact'
  && current?.source === 'artifact'
  && current.artifactId === String(choice?.artifact?.id || '')
  && current.onlyoffice?.documentKey
  && current.onlyoffice.documentKey === choice?.artifact?.onlyoffice?.documentKey
)
