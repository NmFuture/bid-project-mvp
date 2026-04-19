function parseMarkdownLite(content = '') {
  const lines = String(content).split(/\r?\n/)
  const blocks = []
  let paragraph = []
  let listItems = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push({ type: 'p', text: paragraph.join(' ') })
    paragraph = []
  }

  const flushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'ul', items: listItems })
    listItems = []
  }

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd()
    const trimmed = line.trim()

    if (!trimmed) {
      flushParagraph()
      flushList()
      return
    }

    if (trimmed.startsWith('# ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h1', text: trimmed.slice(2).trim() })
      return
    }

    if (trimmed.startsWith('## ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h2', text: trimmed.slice(3).trim() })
      return
    }

    if (trimmed.startsWith('### ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h3', text: trimmed.slice(4).trim() })
      return
    }

    if (trimmed.startsWith('- ')) {
      flushParagraph()
      listItems.push(trimmed.slice(2).trim())
      return
    }

    flushList()
    paragraph.push(trimmed)
  })

  flushParagraph()
  flushList()
  return blocks
}

export default function MarkdownLite({ content = '' }) {
  const blocks = parseMarkdownLite(content)
  if (!blocks.length) {
    return <p className="text-sm text-on-surface-variant">暂无内容</p>
  }

  return (
    <div className="space-y-3 text-sm text-on-surface-variant leading-relaxed">
      {blocks.map((block, index) => {
        if (block.type === 'h1') {
          return (
            <h1 key={index} className="text-xl font-headline font-bold text-on-surface mt-4">
              {block.text}
            </h1>
          )
        }
        if (block.type === 'h2') {
          return (
            <h2 key={index} className="text-lg font-semibold text-on-surface mt-3">
              {block.text}
            </h2>
          )
        }
        if (block.type === 'h3') {
          return (
            <h3 key={index} className="text-base font-semibold text-on-surface mt-2">
              {block.text}
            </h3>
          )
        }
        if (block.type === 'ul') {
          return (
            <ul key={index} className="list-disc pl-5 space-y-1">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{item}</li>
              ))}
            </ul>
          )
        }
        return <p key={index}>{block.text}</p>
      })}
    </div>
  )
}

