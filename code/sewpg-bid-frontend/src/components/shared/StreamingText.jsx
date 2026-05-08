import { useEffect, useState } from 'react'

// 字符级流式输出，模拟 LLM 输出动画。
// text 变化时重新流式；speedMs 控制每字符间隔；showCursor 完成后是否保留闪烁光标。
export default function StreamingText({
  text = '',
  speedMs = 22,
  className = '',
  showCursor = true,
  onDone,
}) {
  const [shown, setShown] = useState('')

  useEffect(() => {
    if (!text) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShown('')
      onDone?.()
      return undefined
    }
    let i = 0
    const id = setInterval(() => {
      i += 1
      setShown(text.slice(0, i))
      if (i >= text.length) {
        clearInterval(id)
        onDone?.()
      }
    }, speedMs)
    return () => clearInterval(id)
  }, [text, speedMs, onDone])

  const streaming = shown.length < text.length

  return (
    <span className={className}>
      {shown}
      {(streaming || showCursor) && (
        <span
          className={`inline-block w-[1px] h-[0.95em] align-[-0.1em] ml-[1px] bg-current ${streaming ? 'animate-stream-cursor' : 'opacity-0'}`}
        />
      )}
    </span>
  )
}
