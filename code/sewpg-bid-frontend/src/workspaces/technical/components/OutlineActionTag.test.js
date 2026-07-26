import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import OutlineActionTag, { getImmediateTooltipPosition } from './OutlineActionTag.js'

test('有招标依据时将状态标签渲染为检索原文按钮', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '必要',
      basis: { searchText: '投标人应提供施工方案' },
      reason: '招标文件明确要求',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /<button[^>]*>必要<\/button>/)
  assert.match(html, /data-tooltip-text="招标文件明确要求；点击定位招标依据"/)
  assert.doesNotMatch(html, /title=/)
  assert.doesNotMatch(html, /find_in_page|material-symbols-outlined/)
})

test('没有招标依据时保留不可点击的状态标签', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '待确认',
      basis: null,
      reason: '人工新增目录项',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /<span[^>]*>待确认<\/span>/)
  assert.match(html, /data-tooltip-text="人工新增目录项"/)
  assert.doesNotMatch(html, /title=/)
  assert.doesNotMatch(html, /<button/)
})

test('建议增加有招标依据时可以点击定位原文', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '建议增加',
      basis: { evidenceId: 'TEN-1:B000123', searchText: '独立提交专题方案' },
      reason: '招标文件要求独立提交',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /<button[^>]*>建议增加<\/button>/)
  assert.match(html, /data-tooltip-text="招标文件要求独立提交；点击定位招标依据"/)
  assert.doesNotMatch(html, /title=/)
})

test('建议删除仅悬停时立即显示浅色理由提示', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '建议删除',
      basis: { evidenceId: 'TEN-1:B000123', searchText: '原文' },
      reason: '与已有章节重复',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /data-tooltip-text="与已有章节重复"/)
  assert.doesNotMatch(html, /<button/)
  assert.doesNotMatch(html, /title=/)
  assert.doesNotMatch(html, /点击定位招标依据/)
})

test('必要来自专家经验时仅悬停立即显示浅色理由提示', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '必要',
      basis: null,
      reason: '成熟投标方案所需的专业组织章节',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.match(html, /data-tooltip-text="成熟投标方案所需的专业组织章节"/)
  assert.doesNotMatch(html, /<button/)
  assert.doesNotMatch(html, /title=/)
})

test('没有招标依据也没有理由时保持普通状态标签', () => {
  const html = renderToStaticMarkup(
    createElement(OutlineActionTag, {
      action: '必要',
      basis: null,
      reason: '',
      onFocusBasis: () => {},
    }),
  )

  assert.match(html, /^<span/)
  assert.doesNotMatch(html, /<details/)
  assert.doesNotMatch(html, /<button/)
})

test('即时提示根据滚动区剩余空间选择上下方向并保持在目录边界内', () => {
  const bounds = { top: 100, right: 700, bottom: 600, left: 100, width: 600, height: 500 }

  assert.deepEqual(
    getImmediateTooltipPosition(
      { top: 140, right: 560, bottom: 166 },
      bounds,
      { width: 1280, height: 720 },
    ),
    { top: 170, bottom: null, right: 720, maxWidth: 320, maxHeight: 240 },
  )
  assert.deepEqual(
    getImmediateTooltipPosition(
      { top: 570, right: 560, bottom: 596 },
      bounds,
      { width: 1280, height: 720 },
    ),
    { top: null, bottom: 154, right: 720, maxWidth: 320, maxHeight: 240 },
  )
})
