import { Fragment } from 'react'

export default function HighlightedText({ text = '', regex, highlightClassName = '' }) {
  if (!regex || !(regex instanceof RegExp) || !text) {
    return <>{text || ''}</>
  }

  const pattern = regex.global ? regex : new RegExp(regex.source, `${regex.flags}g`)
  const matches = [...text.matchAll(pattern)]
  if (!matches.length) return <>{text}</>

  let cursor = 0
  const nodes = []

  matches.forEach((match, index) => {
    const start = match.index ?? 0
    const value = match[0]
    const end = start + value.length

    if (start > cursor) {
      nodes.push(
        <Fragment key={`t-${index}`}>{text.slice(cursor, start)}</Fragment>,
      )
    }

    nodes.push(
      <strong key={`h-${index}`} className={highlightClassName}>
        {value}
      </strong>,
    )
    cursor = end
  })

  if (cursor < text.length) {
    nodes.push(<Fragment key="tail">{text.slice(cursor)}</Fragment>)
  }

  return <>{nodes}</>
}

