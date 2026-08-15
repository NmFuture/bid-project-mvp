import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import { asArray } from './technicalGapRecognitionHelpers'
import MaterialCandidateCard from './technicalGapMaterialCard'

// AI 填写参考素材选择弹窗（产品裁决：点素材卡上的 AI填写 → 弹窗选参考素材 → 执行）。
// 弹窗内出现哪些素材的规则后续由匹配规则定义，当前沿用本目录项的推荐/召回候选池。
// 单一职责（产品意见 2026-07-17）：弹窗只做「挑 AI 参考素材」一件事——卡上不出现
// 「选择（选用为章节素材）」按钮，整卡点击即勾选/取消，避免「勾选」与「选择」两个概念混淆。
function AiFillReferenceModal({
  open,
  blankTitle,
  sourceRoutingSummary,
  tenderDocumentState,
  candidates,
  referenceIds,
  busy,
  onToggle,
  onPreview,
  onConfirm,
  onClose,
  onUpload,
  uploadBusy,
  confirmBlockReason,
}) {
  if (!open) return null
  const usesTenderDocument = Boolean(tenderDocumentState?.required)
  const missingTenderDocument = Boolean(tenderDocumentState?.missingSource)
  const tenderDocumentNames = asArray(tenderDocumentState?.documentNames)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-2 sm:p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="technical-ai-fill-modal-title" className="flex max-h-[calc(100dvh-1rem)] w-full max-w-4xl flex-col overflow-hidden overscroll-contain rounded-lg bg-surface shadow-[0_12px_28px_rgba(13,33,55,0.14)] sm:max-h-[calc(100dvh-2rem)]">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-3 py-4 sm:px-5">
          <div className="min-w-0">
            <h3 id="technical-ai-fill-modal-title" className="text-lg font-headline font-bold text-on-surface">AI 填写</h3>
            <p className="mt-1 truncate text-xs text-on-surface-variant" title={blankTitle}>
              待填写对象：{blankTitle || '待填写空表/Word'}
            </p>
          </div>
          <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="rounded-md border border-secondary/20 bg-secondary-container/30 px-3 py-2 text-[11px] text-on-secondary-container">
            勾选结果会锁定为本次 AI 填写的唯一素材范围，不会自动扩大到其他素材。
          </div>
          {sourceRoutingSummary ? (
            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] leading-relaxed text-on-surface-variant">
              {sourceRoutingSummary}
            </div>
          ) : null}
          {usesTenderDocument ? (
            <div className={`mt-2 rounded-md px-3 py-2 text-[11px] leading-relaxed ${missingTenderDocument ? 'bg-error-container text-on-error-container' : 'bg-primary-container/45 text-on-primary-container'}`}>
              <div className="font-semibold">使用项目招标文件全文</div>
              <div className="mt-0.5">
                {missingTenderDocument
                  ? '项目当前没有可读取的招标文件，请先在技术标解析中补充或替换招标文件并重新解析。'
                  : tenderDocumentNames.length
                    ? `${tenderDocumentNames.join('、')}（共 ${tenderDocumentState.documentCount} 份）`
                    : '执行时将读取解析阶段上传的完整招标文件及其全文、表格解析结果。'}
              </div>
            </div>
          ) : null}
          <div className="mt-3 space-y-2">
            {candidates.length ? candidates.map((material) => {
              const materialId = String(material.id || material.materialId || '').trim()
              const checked = referenceIds.includes(materialId)
              return (
                <MaterialCandidateCard
                  key={materialId || material.name}
                  material={material}
                  isSelected={false}
                  busy={busy || !materialId}
                  selecting={false}
                  onPreview={onPreview}
                  onSelect={null}
                  fillable={false}
                  onCardClick={materialId && !busy ? () => onToggle(materialId) : null}
                  leading={(
                    <label
                      className="flex shrink-0 items-center gap-1 pt-0.5"
                      title="勾选后作为本次 AI 填写的参考素材"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={busy || !materialId}
                        onChange={() => onToggle(materialId)}
                        className="h-4 w-4 shrink-0 accent-primary"
                        aria-label={`勾选 ${material.name || material.cleanedFileName || materialId} 用于 AI 填写`}
                      />
                      {checked ? (
                        <span className="rounded bg-secondary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-secondary-container">
                          用于AI
                        </span>
                      ) : null}
                    </label>
                  )}
                />
              )
            }) : (
              <div className="rounded-md bg-surface-container-low px-3 py-2 text-[11px] text-outline">
                {usesTenderDocument && !missingTenderDocument
                  ? '本次无需额外选择素材，AI 将读取项目招标文件全文进行填写。'
                  : '暂无推荐素材，可先在目录项底部搜索或上传素材后再发起 AI 填写。'}
              </div>
            )}
          </div>
          {onUpload ? (
            <div className="mt-3 rounded-md border border-dashed border-surface-container-high bg-surface-container-low/50 px-3 py-2">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-on-surface">上传补充素材</div>
                  <div className="mt-0.5 text-[11px] text-outline">
                    自动匹配不准时可手动补料：上传的文件会存入项目素材库，并自动勾选为本次 AI 填写的参考素材。
                  </div>
                </div>
                <label className={`inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container ${busy || uploadBusy ? 'pointer-events-none opacity-50' : ''}`}>
                  <span className="material-symbols-outlined text-[16px]">upload_file</span>
                  {uploadBusy ? '上传中...' : '上传素材'}
                  <input
                    type="file"
                    multiple
                    accept=".docx,.xlsx,.xls,.pdf"
                    className="hidden"
                    disabled={busy || uploadBusy}
                    onChange={(event) => {
                      const files = event.target.files
                      event.target.value = ''
                      if (files?.length) onUpload(files)
                    }}
                  />
                </label>
              </div>
            </div>
          ) : null}
        </div>
        <div className="flex flex-col gap-3 border-t border-surface-container-high bg-surface-container-low px-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="flex flex-wrap gap-1.5">
            <span className="rounded bg-secondary-container px-2 py-0.5 text-[10px] font-semibold text-on-secondary-container">
              已选 {referenceIds.length} 份参考素材
            </span>
            {usesTenderDocument && !missingTenderDocument ? (
              <span className="rounded bg-primary-container px-2 py-0.5 text-[10px] font-semibold text-on-primary-container">
                招标文件 {tenderDocumentState.documentCount || '全部'} 份
              </span>
            ) : null}
          </div>
          <div className="flex w-full gap-2 sm:w-auto">
            <Button type="button" onClick={onClose} disabled={busy} variant="quiet">取消</Button>
            <Button
              type="button"
              onClick={onConfirm}
              disabled={busy || missingTenderDocument || Boolean(confirmBlockReason)}
              title={confirmBlockReason || ''}
              variant="primary"
            >
              {busy ? '处理中...' : missingTenderDocument ? '缺少招标文件' : '开始 AI 填写'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AiFillReferenceModal
