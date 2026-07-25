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

test('建议增加有招标依据时可以点击定位原文', () => {
  const html = renderToStaticMarkup(
    OutlineActionTag({
      action: '建议增加',
      basis: { evidenceId: 'TEN-1:B000123', searchText: '独立提交专题方案' },
      reason: '招标文件要求独立提交',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<button/)
  assert.match(html, />建议增加<\/button>$/)
})

test('建议删除即使误带招标依据也只显示悬浮理由', () => {
  const html = renderToStaticMarkup(
    OutlineActionTag({
      action: '建议删除',
      basis: { evidenceId: 'TEN-1:B000123', searchText: '原文' },
      reason: '与已有章节重复',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /title="与已有章节重复"/)
  assert.doesNotMatch(html, /<button/)
  assert.doesNotMatch(html, /点击定位招标依据/)
})

test('必要来自专家经验时只显示悬浮保留理由', () => {
  const html = renderToStaticMarkup(
    OutlineActionTag({
      action: '必要',
      basis: null,
      reason: '成熟投标方案所需的专业组织章节',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /title="成熟投标方案所需的专业组织章节"/)
  assert.doesNotMatch(html, /<button/)
})
