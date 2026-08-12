import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

test('技术标导出工具栏按版本、Word、PDF、重新生成和全屏顺序排列', () => {
  const versionIndex = editorSource.indexOf('aria-label="下载版本"')
  const wordIndex = editorSource.indexOf('onClick={handleDownloadWord}', versionIndex)
  const pdfIndex = editorSource.indexOf('onClick={handlePreparePdf}', wordIndex)
  const regenerateIndex = editorSource.indexOf('onClick={handleRequestRegenerate}', pdfIndex)
  const fullscreenIndex = editorSource.indexOf(
    'onClick={() => setTechnicalPreviewFullscreen((value) => !value)}',
    regenerateIndex,
  )

  assert.ok(versionIndex >= 0)
  assert.ok(versionIndex < wordIndex)
  assert.ok(wordIndex < pdfIndex)
  assert.ok(pdfIndex < regenerateIndex)
  assert.ok(regenerateIndex < fullscreenIndex)
})

test('技术标导出工具栏移除编辑状态并缩短下载按钮文案', () => {
  assert.doesNotMatch(editorSource, /editorModeLabel/)
  assert.match(editorSource, /\{wordPreparing \? '生成中\.\.\.' : 'Word'\}/)
  assert.match(editorSource, /\{pdfPreparing \? '生成中\.\.\.' : 'PDF'\}/)
  assert.doesNotMatch(editorSource, /下载Word|下载PDF|OnlyOffice 在线编辑/)
})
