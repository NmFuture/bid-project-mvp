import Button from '../../../components/ui/Button'
import { Dialog, DialogBody, DialogHeader } from '../../../components/ui/Dialog'

export default function TechnicalTaskProgressDialog({
  open,
  title,
  active = false,
  stopping = false,
  onClose,
  onStop,
  children,
}) {
  if (!open) return null

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      className="max-h-[min(720px,calc(100dvh-2rem))]"
    >
      {/* DialogHeader 把 children 整体塞进标题块，且该块按内容宽度收缩；
          先让标题块撑满，再在里面排一行：标题贴左，带文字的「关闭」贴右。 */}
      <DialogHeader className="items-center py-3.5 [&>div:first-child]:flex-1">
        <div className="flex w-full items-center justify-between gap-3">
          <h3 className="truncate font-headline text-base font-semibold text-on-surface">{title}</h3>
          <Button type="button" onClick={onClose} variant="ghost" size="sm" className="shrink-0">关闭</Button>
        </div>
      </DialogHeader>
      <DialogBody className="space-y-4 p-5 sm:p-6">
        {children}
        {active && onStop ? (
          <div className="flex justify-end pt-1">
            <Button
              type="button"
              onClick={onStop}
              disabled={stopping}
              variant="dangerQuiet"
              size="stage"
            >
              {stopping ? '停止中...' : '停止'}
            </Button>
          </div>
        ) : null}
      </DialogBody>
    </Dialog>
  )
}
