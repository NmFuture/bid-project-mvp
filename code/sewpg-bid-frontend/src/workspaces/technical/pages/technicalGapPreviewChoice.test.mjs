import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isSameArtifactPreviewSession,
  resolveGapPreviewChoice,
} from './technicalGapPreviewChoice.js'

const materialChoice = { key: 'material:RAW-1', kind: 'material', material: { id: 'RAW-1' } }
const appendixChoice = { key: 'appendix:APPX-1', kind: 'appendix', blankSource: { id: 'APPX-1' } }

test('预览项解析：未选 key 时回落到第一个选项', () => {
  const result = resolveGapPreviewChoice({
    choices: [materialChoice, appendixChoice],
    manualPreviewChoice: null,
    selectedId: 'GAP-1',
    previewChoiceKey: '',
  })
  assert.equal(result.manualActive, null)
  assert.equal(result.effectiveKey, 'material:RAW-1')
  assert.equal(result.selected, materialChoice)
  assert.deepEqual(result.visible, [materialChoice, appendixChoice])
})

test('预览项解析：手工预览项同目录项且同 key 才生效，并补进可见列表', () => {
  const manual = { key: 'material:RAW-9:manual', kind: 'material', itemId: 'GAP-1', material: { id: 'RAW-9' } }
  const active = resolveGapPreviewChoice({
    choices: [materialChoice],
    manualPreviewChoice: manual,
    selectedId: 'GAP-1',
    previewChoiceKey: 'material:RAW-9:manual',
  })
  assert.equal(active.manualActive, manual)
  assert.equal(active.selected, manual)
  assert.deepEqual(active.visible, [materialChoice, manual])

  // 切到别的目录项后手工项失效，回落到目录项自带选项
  const otherItem = resolveGapPreviewChoice({
    choices: [materialChoice],
    manualPreviewChoice: manual,
    selectedId: 'GAP-2',
    previewChoiceKey: 'material:RAW-9:manual',
  })
  assert.equal(otherItem.manualActive, null)
  assert.equal(otherItem.selected, materialChoice)
  assert.deepEqual(otherItem.visible, [materialChoice])

  // key 已指回自带选项时手工项同样失效
  const otherKey = resolveGapPreviewChoice({
    choices: [materialChoice],
    manualPreviewChoice: manual,
    selectedId: 'GAP-1',
    previewChoiceKey: 'material:RAW-1',
  })
  assert.equal(otherKey.manualActive, null)
  assert.equal(otherKey.selected, materialChoice)
})

test('预览项解析：空选项列表时选中为 null、对比为 null', () => {
  const result = resolveGapPreviewChoice({
    choices: [],
    manualPreviewChoice: null,
    selectedId: 'GAP-1',
    previewChoiceKey: '',
  })
  assert.equal(result.selected, null)
  assert.equal(result.comparison, null)
})

test('同一产物同一 documentKey 不重载预览会话（读 ref 避免打断在线编辑）', () => {
  const choice = {
    kind: 'artifact',
    artifact: { id: 'ART-1', onlyoffice: { documentKey: 'key-v1' } },
  }
  const current = {
    source: 'artifact',
    artifactId: 'ART-1',
    onlyoffice: { documentKey: 'key-v1' },
  }
  assert.equal(isSameArtifactPreviewSession(choice, current), true)
  // 版本变了（documentKey 不同）必须重载
  assert.equal(isSameArtifactPreviewSession(choice, { ...current, onlyoffice: { documentKey: 'key-v2' } }), false)
  // 换了产物必须重载
  assert.equal(isSameArtifactPreviewSession(choice, { ...current, artifactId: 'ART-2' }), false)
  // 旧会话没有 documentKey 时不算同一会话
  assert.equal(isSameArtifactPreviewSession(choice, { ...current, onlyoffice: {} }), false)
  // 非产物预览一律不走这个短路
  assert.equal(isSameArtifactPreviewSession(materialChoice, current), false)
  assert.equal(isSameArtifactPreviewSession(choice, null), false)
})
