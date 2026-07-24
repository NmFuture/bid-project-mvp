import assert from 'node:assert/strict'
import test from 'node:test'
import { renderToStaticMarkup } from 'react-dom/server'

import OutlineActionTag from './OutlineActionTag.js'

test('有招标依据时将状态标签渲染为检索原文按钮', () => {
  const html = renderToStaticMarkup(
    OutlineActionTag({
      action: '必要',
      basis: { searchText: '投标人应提供施工方案' },
      reason: '招标文件明确要求',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<button/)
  assert.match(html, />必要<\/button>$/)
  assert.match(html, /点击定位招标依据/)
  assert.doesNotMatch(html, /find_in_page|material-symbols-outlined/)
})

test('没有招标依据时保留不可点击的状态标签', () => {
  const html = renderToStaticMarkup(
    OutlineActionTag({
      action: '待确认',
      basis: null,
      reason: '人工新增目录项',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, />待确认<\/span>$/)
  assert.doesNotMatch(html, /<button/)
})
