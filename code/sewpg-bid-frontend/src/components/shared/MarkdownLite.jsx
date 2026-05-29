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

  const flushInlineBlocks = () => {
    flushParagraph()
    flushList()
  }

  const parseTableRow = (line) => {
    const normalized = line.trim().replace(/^\|/, '').replace(/\|$/, '')
    return normalized.split('|').map((cell) => cell.trim())
  }

  const isTableSeparator = (line) => {
    const cells = parseTableRow(line)
    return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  }

  const isTableStart = (index) => {
    const current = lines[index]?.trim()
    const next = lines[index + 1]?.trim()
    return Boolean(
      current
      && next
      && current.includes('|')
      && next.includes('|')
      && isTableSeparator(next),
    )
  }

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index]
    const line = rawLine.trimEnd()
    const trimmed = line.trim()

    if (!trimmed) {
      flushParagraph()
      flushList()
      continue
    }

    if (isTableStart(index)) {
      flushInlineBlocks()
      const headers = parseTableRow(trimmed)
      const rows = []
      index += 2
      while (index < lines.length) {
        const rowLine = lines[index].trim()
        if (!rowLine || !rowLine.includes('|')) {
          index -= 1
          break
        }
        const cells = parseTableRow(rowLine)
        rows.push(headers.map((_, cellIndex) => cells[cellIndex] || ''))
        index += 1
      }
      if (index >= lines.length) index -= 1
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    if (trimmed.startsWith('# ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h1', text: trimmed.slice(2).trim() })
      continue
    }

    if (trimmed.startsWith('## ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h2', text: trimmed.slice(3).trim() })
      continue
    }

    if (trimmed.startsWith('### ')) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h3', text: trimmed.slice(4).trim() })
      continue
    }

    if (trimmed.startsWith('- ')) {
      flushParagraph()
      listItems.push(trimmed.slice(2).trim())
      continue
    }

    flushList()
    paragraph.push(trimmed)
  }

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
        if (block.type === 'table') {
          return (
            <div key={index} className="overflow-x-auto rounded-lg border border-surface-container-high">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr>
                    {block.headers.map((header, headerIndex) => (
                      <th key={headerIndex} className="px-3 py-2 align-top">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.length > 0 ? (
                    block.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} className="px-3 py-2 align-top">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="px-3 py-2 text-outline" colSpan={block.headers.length}>
                        暂无数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )
        }
        return <p key={index}>{block.text}</p>
      })}
    </div>
  )
}
