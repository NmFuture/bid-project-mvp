import { useEffect, useState } from 'react'
import Button from '../ui/Button'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from '../ui/Dialog'
import BidProgressPanel from './BidProgressPanel'
import { progressElapsedLine } from '../../utils/progressDuration'

// 素材匹配（目录确认后触发缺口识别）。这条链路是一次性阻塞请求，后端没有中间进度可查，
// 所以百分比是按已运行时间的估算：渐进逼近 92% 后等真实结果，绝不假装已经完成。
// 计时与文案用的都是真实数据——起点是本次点击时刻，目录项数量来自当前目录。
const EXPECTED_SECONDS = 60
const RUNNING_CAP = 92

const estimatePercentage = (elapsedSeconds) => {
  const elapsed = Math.max(0, Number(elapsedSeconds) || 0)
  return RUNNING_CAP * (1 - Math.exp(-elapsed / (EXPECTED_SECONDS / 2.5)))
}

export default function MaterialMatchProgressModal({
  open,
  running,
  error,
  itemCount = 0,
  startedAtMs = 0,
  finishedAtMs = 0,
  onClose,
}) {
  const [nowMs, setNowMs] = useState(() => Date.now())

  // 弹窗常驻在页面里，nowMs 初值是页面挂载时刻；打开后先补一拍再按秒走，避免首帧用旧时间。
  useEffect(() => {
    if (!open || !running) return undefined
    const catchUp = window.setTimeout(() => setNowMs(Date.now()), 0)
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => {
      window.clearTimeout(catchUp)
      window.clearInterval(timer)
    }
  }, [open, running])

  if (!open) return null

  const failed = Boolean(error)
  const title = failed ? '素材匹配失败' : running ? '正在执行素材匹配' : '素材匹配已完成'
  const endMs = finishedAtMs > 0 ? finishedAtMs : nowMs
  const elapsedSeconds = startedAtMs > 0 ? Math.max(0, (endMs - startedAtMs) / 1000) : 0
  const scopeText = itemCount > 0 ? `，共 ${itemCount} 个目录项` : ''
  const detail = failed
    ? '素材匹配未完成，目录确认结果已保留。'
    : running
      ? `正在按已确认目录匹配素材${scopeText}`
      : `素材匹配已完成${scopeText}`

  return (
    <Dialog open={open} onClose={running ? undefined : onClose} size="sm">
      <DialogHeader onClose={running ? undefined : onClose}>
        <h3 className="text-lg font-headline font-bold text-on-surface">{title}</h3>
      </DialogHeader>
      <DialogBody className="space-y-4 p-5">
        <BidProgressPanel
          tone={failed ? 'danger' : running ? 'running' : 'success'}
          detail={detail}
          elapsedText={progressElapsedLine(elapsedSeconds, { finished: !running })}
          percentage={running ? estimatePercentage(elapsedSeconds) : 100}
          running={running}
        />
        {running ? (
          <p className="text-xs text-outline">匹配完成后会自动进入素材匹配页，请勿关闭页面。</p>
        ) : null}
        {failed ? (
          <div className="border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
            {error}
          </div>
        ) : null}
      </DialogBody>
      {running ? null : (
        <DialogFooter>
          <Button type="button" onClick={onClose} variant={failed ? 'quiet' : 'primary'}>关闭</Button>
        </DialogFooter>
      )}
    </Dialog>
  )
}
