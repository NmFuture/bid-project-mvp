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

export default function MarkdownLite({ content = '', compact = false }) {
  const blocks = parseMarkdownLite(content)
  const styles = compact
    ? {
        empty: 'text-[13px] leading-[1.6] text-on-surface-variant',
        root: 'space-y-2.5 text-[13px] leading-[1.6] text-on-surface-variant',
        h1: 'text-lg leading-[1.5] font-headline font-bold text-on-surface mt-3',
        h2: 'text-[15px] leading-[1.5] font-semibold text-on-surface mt-2.5',
        h3: 'text-[14px] leading-[1.5] font-semibold text-on-surface mt-2',
        table: 'w-full min-w-[640px] text-left text-[13px] leading-[1.6]',
      }
    : {
        empty: 'text-sm text-on-surface-variant',
        root: 'space-y-3 text-sm text-on-surface-variant leading-relaxed',
        h1: 'text-xl font-headline font-bold text-on-surface mt-4',
        h2: 'text-lg font-semibold text-on-surface mt-3',
        h3: 'text-base font-semibold text-on-surface mt-2',
        table: 'w-full min-w-[640px] text-left text-sm',
      }

  if (!blocks.length) {
    return <p className={styles.empty}>暂无内容</p>
  }

  return (
    <div className={styles.root}>
      {blocks.map((block, index) => {
        if (block.type === 'h1') {
          return (
            <h1 key={index} className={styles.h1}>
              {block.text}
            </h1>
          )
        }
        if (block.type === 'h2') {
          return (
            <h2 key={index} className={styles.h2}>
              {block.text}
            </h2>
          )
        }
        if (block.type === 'h3') {
          return (
            <h3 key={index} className={styles.h3}>
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
              <table className={styles.table}>
                <thead>
                  <tr>
                    {block.headers.map((header, headerIndex) => (
                      <th key={headerIndex} className="!h-auto !font-normal px-3 py-1.5 align-top leading-[1.6]">
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
                          <td key={cellIndex} className="!h-auto px-3 py-1.5 align-top leading-[1.6]">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="!h-auto px-3 py-1.5 text-outline" colSpan={block.headers.length}>
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
