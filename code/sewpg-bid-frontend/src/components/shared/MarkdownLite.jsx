// 轻量 Markdown 渲染：支持标题、列表、引用、表格、分隔线，以及行内
// **加粗** / *斜体* / `代码`。技术标 Wiki 文件卡片的 AI 内容预览（导读引用、
// **要点** / **关键参数** 等加粗小标题、> 引用、--- 分隔线）都依赖这些规则。

// 把单行文本拆成行内 token，渲染成带 <strong>/<em>/<code> 的 React 节点。
// 处理 \\| 转义（表格单元格里的竖线）。规则简单但够用：不嵌套同类标记。
function renderInline(text = '') {
  const source = String(text).replace(/\\\|/g, '|')
  const nodes = []
  // 依次匹配 **bold** / *italic* / `code`，其余按纯文本切片。
  const pattern = /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)/g
  let lastIndex = 0
  let match
  let key = 0
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(source.slice(lastIndex, match.index))
    }
    if (match[2] !== undefined) {
      nodes.push(<strong key={`b${key}`} className="font-semibold text-on-surface">{match[2]}</strong>)
    } else if (match[3] !== undefined) {
      nodes.push(<em key={`i${key}`}>{match[3]}</em>)
    } else if (match[4] !== undefined) {
      nodes.push(
        <code key={`c${key}`} className="rounded bg-surface-container-high px-1 py-0.5 text-[0.92em]">
          {match[4]}
        </code>,
      )
    }
    lastIndex = pattern.lastIndex
    key += 1
  }
  if (lastIndex < source.length) {
    nodes.push(source.slice(lastIndex))
  }
  return nodes.length ? nodes : source
}

function nestListItems(items = []) {
  const roots = []
  const stack = []
  items.forEach((item) => {
    const node = { text: item.text, children: [] }
    const depth = Math.min(Math.max(0, item.depth), stack.length)
    if (depth === 0) {
      roots.push(node)
    } else {
      stack[depth - 1].children.push(node)
    }
    stack[depth] = node
    stack.length = depth + 1
  })
  return roots
}

function renderListItems(items = []) {
  return items.map((item, index) => (
    <li key={index}>
      {renderInline(item.text)}
      {item.children.length > 0 ? (
        <ul className="mt-1 list-disc space-y-1 pl-5">
          {renderListItems(item.children)}
        </ul>
      ) : null}
    </li>
  ))
}

function parseMarkdownLite(content = '') {
  const lines = String(content).split(/\r?\n/)
  const blocks = []
  let paragraph = []
  let listItems = []
  let quoteLines = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push({ type: 'p', text: paragraph.join(' ') })
    paragraph = []
  }

  const flushList = () => {
    if (!listItems.length) return
    blocks.push({ type: 'ul', items: nestListItems(listItems) })
    listItems = []
  }

  const flushQuote = () => {
    if (!quoteLines.length) return
    blocks.push({ type: 'quote', text: quoteLines.join(' ') })
    quoteLines = []
  }

  const flushInlineBlocks = () => {
    flushParagraph()
    flushList()
    flushQuote()
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
      flushInlineBlocks()
      continue
    }

    // 水平分隔线：--- / *** / ___（整行）。
    if (/^([-*_])\1{2,}$/.test(trimmed.replace(/\s+/g, ''))) {
      flushInlineBlocks()
      blocks.push({ type: 'hr' })
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

    // 引用块：连续的 > 行合并成一个引用（中间不空行）。
    if (trimmed.startsWith('>')) {
      flushParagraph()
      flushList()
      quoteLines.push(trimmed.replace(/^>\s?/, '').trim())
      continue
    }

    if (trimmed.startsWith('# ')) {
      flushInlineBlocks()
      blocks.push({ type: 'h1', text: trimmed.slice(2).trim() })
      continue
    }

    if (trimmed.startsWith('## ')) {
      flushInlineBlocks()
      blocks.push({ type: 'h2', text: trimmed.slice(3).trim() })
      continue
    }

    if (trimmed.startsWith('### ')) {
      flushInlineBlocks()
      blocks.push({ type: 'h3', text: trimmed.slice(4).trim() })
      continue
    }

    const listMatch = rawLine.match(/^(\s*)[-*]\s+(.+)$/)
    if (listMatch) {
      flushParagraph()
      flushQuote()
      const indentation = listMatch[1].replace(/\t/g, '    ').length
      listItems.push({ text: listMatch[2].trim(), depth: Math.floor(indentation / 4) })
      continue
    }

    flushList()
    flushQuote()
    paragraph.push(trimmed)
  }

  flushInlineBlocks()
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
              {renderInline(block.text)}
            </h1>
          )
        }
        if (block.type === 'h2') {
          return (
            <h2 key={index} className={styles.h2}>
              {renderInline(block.text)}
            </h2>
          )
        }
        if (block.type === 'h3') {
          return (
            <h3 key={index} className={styles.h3}>
              {renderInline(block.text)}
            </h3>
          )
        }
        if (block.type === 'hr') {
          return <hr key={index} className="border-0 border-t border-outline-variant/45 my-1" />
        }
        if (block.type === 'quote') {
          return (
            <blockquote
              key={index}
              className="border-l-2 border-primary/40 bg-primary/5 rounded-r px-3 py-2 text-on-surface-variant"
            >
              {renderInline(block.text)}
            </blockquote>
          )
        }
        if (block.type === 'ul') {
          return (
            <ul key={index} className="list-disc pl-5 space-y-1">
              {renderListItems(block.items)}
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
                        {renderInline(header)}
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
                            {renderInline(cell)}
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
        return <p key={index}>{renderInline(block.text)}</p>
      })}
    </div>
  )
}
