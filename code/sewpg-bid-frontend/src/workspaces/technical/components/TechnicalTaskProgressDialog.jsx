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
      <DialogHeader className="items-center py-3.5">
        <h3 className="truncate font-headline text-base font-semibold text-on-surface">{title}</h3>
        <Button type="button" onClick={onClose} variant="ghost" size="sm">关闭</Button>
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
