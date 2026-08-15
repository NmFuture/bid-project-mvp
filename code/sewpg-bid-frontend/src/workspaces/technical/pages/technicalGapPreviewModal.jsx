import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import { asObjectArray, isEditableArtifactChoice } from './technicalGapRecognitionHelpers'

const previewKindLabels = {
  material: '素材预览',
  appendix: '未填写预览',
  blankMaterial: '未填写预览',
  artifact: '结果预览',
}

const previewKindIcons = {
  material: 'description',
  appendix: 'table_view',
  blankMaterial: 'description',
  artifact: 'task',
}

function PreviewDocumentPane({
  eyebrow,
  title,
  icon,
  loading,
  session,
  error,
  mode = 'view',
}) {
  return (
    <section className="flex min-h-[24rem] min-w-0 flex-col overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest lg:min-h-[35rem]">
      <div className="flex min-h-[64px] shrink-0 items-center gap-3 border-b border-surface-container-high px-4 py-3">
        <span className="material-symbols-outlined flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary-fixed text-[20px] text-primary">
          {icon}
        </span>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-primary">{eyebrow}</div>
          <h4 className="mt-0.5 truncate text-sm font-semibold text-on-surface" title={title}>{title}</h4>
        </div>
        {mode === 'edit' ? (
          <span className="ml-auto shrink-0 rounded bg-primary-fixed px-2 py-0.5 text-[10px] font-semibold text-primary">
            可编辑 · 自动保存
          </span>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 bg-surface-container-low p-2">
        {loading ? (
          <div className="flex h-full min-h-[20rem] items-center justify-center rounded-md bg-surface-container-lowest px-4 text-center lg:min-h-[30rem] lg:px-6">
            <div>
              <span className="material-symbols-outlined text-3xl text-primary">hourglass_empty</span>
              <p className="mt-2 text-sm text-on-surface-variant">正在加载预览...</p>
            </div>
          </div>
        ) : session?.onlyoffice ? (
          <OnlyOfficeEmbed
            session={session.onlyoffice}
            mode={mode}
            className="h-full min-h-[480px] w-full rounded-md border border-surface-container-high bg-white"
            onError={() => {}}
          />
        ) : (
          <div className="flex h-full min-h-[480px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
            <p className="max-w-md text-sm text-on-surface-variant">
              {error || '当前文档暂时无法预览，请检查素材是否已清洗为 Word。'}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

function TechnicalPreviewModal({
  open,
  sectionTitle,
  selectedPreviewChoice,
  comparison,
  previewLoading,
  previewSession,
  previewError,
  referencePreviewLoading,
  referencePreviewSession,
  referencePreviewError,
  onClose,
  reviewQueue,
  reviewCurrentId,
  onReviewStep,
  onReviewPass,
  reviewBusy,
}) {
  if (!open) return null
  const comparing = Boolean(comparison)
  // 待审核队列：一键填完是一批产物，在弹窗里连着审，不用退出去逐条点目录
  const queue = asObjectArray(reviewQueue)
  const queueIndex = queue.findIndex((item) => item?.id === reviewCurrentId)
  const showQueue = comparing && queue.length > 1

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-2 sm:p-4">
      <section role="dialog" aria-modal="true" aria-labelledby="technical-preview-modal-title" className="flex h-[calc(100dvh-1rem)] w-full max-w-[1800px] flex-col overflow-hidden overscroll-contain rounded-lg bg-surface shadow-[0_12px_28px_rgba(13,33,55,0.14)] sm:h-[min(94dvh,980px)] sm:w-[min(96vw,1800px)]">
        <div className="flex min-h-[68px] shrink-0 flex-col gap-3 border-b border-surface-container-high bg-surface px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="min-w-0">
            <h3 id="technical-preview-modal-title" className="truncate text-base font-semibold text-on-surface">
              {comparing ? 'AI 填写结果对比' : (selectedPreviewChoice?.title || '文档预览')}
            </h3>
            <p className="mt-1 truncate text-xs text-outline" title={sectionTitle || selectedPreviewChoice?.subtitle || ''}>
              {comparing
                ? (sectionTitle || '对照填写前参考稿与 AI 填写结果')
                : `${previewKindLabels[selectedPreviewChoice?.kind] || '预览'} · ${selectedPreviewChoice?.subtitle || '-'}`}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {showQueue ? (
              <div className="flex items-center gap-1 rounded-md bg-surface-container-low px-1 py-0.5">
                <IconButton
                  aria-label="上一条待审核"
                  icon="chevron_left"
                  onClick={() => onReviewStep?.(-1)}
                  disabled={reviewBusy}
                  variant="quiet"
                />
                <span className="min-w-12 text-center text-[11px] tabular-nums text-on-surface-variant">
                  {queueIndex >= 0 ? queueIndex + 1 : '-'}/{queue.length}
                </span>
                <IconButton
                  aria-label="下一条待审核"
                  icon="chevron_right"
                  onClick={() => onReviewStep?.(1)}
                  disabled={reviewBusy}
                  variant="quiet"
                />
              </div>
            ) : null}
            {comparing && onReviewPass ? (
              <Button
                type="button"
                onClick={onReviewPass}
                disabled={reviewBusy}
                title="确认本条 AI 填写结果无误，定案后自动看下一条"
                size="sm"
                variant="primary"
              >
                复核通过
              </Button>
            ) : null}
            <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
          </div>
        </div>

        <div className={`min-h-0 flex-1 overflow-auto bg-surface-container-low p-3 ${comparing ? 'grid gap-3 lg:grid-cols-2' : ''}`}>
          {comparing ? (
            <>
              <PreviewDocumentPane
                eyebrow="填写前 · 参考稿"
                title={comparison.reference.title || '待填写文档'}
                icon={previewKindIcons[comparison.reference.kind] || 'description'}
                loading={referencePreviewLoading}
                session={referencePreviewSession}
                error={referencePreviewError}
              />
              <PreviewDocumentPane
                eyebrow="填写后 · AI 结果"
                title={comparison.result.title || 'AI 填写结果'}
                icon="auto_awesome"
                loading={previewLoading}
                session={previewSession}
                error={previewError}
                mode={isEditableArtifactChoice(comparison.result) ? 'edit' : 'view'}
              />
            </>
          ) : selectedPreviewChoice ? (
            <PreviewDocumentPane
              eyebrow={previewKindLabels[selectedPreviewChoice.kind] || '文档预览'}
              title={selectedPreviewChoice.title || '文档预览'}
              icon={previewKindIcons[selectedPreviewChoice.kind] || 'description'}
              loading={previewLoading}
              session={previewSession}
              error={previewError}
              mode={isEditableArtifactChoice(selectedPreviewChoice) ? 'edit' : 'view'}
            />
          ) : (
            <div className="flex h-full min-h-[520px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
              <p className="max-w-md text-sm text-on-surface-variant">当前目录项还没有可预览的素材、空表或处理产物。</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

export default TechnicalPreviewModal
