import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

test('技术标导出工具栏按版本、Word、PDF、重新生成索引、重新生成正文和全屏顺序排列', () => {
  const versionIndex = editorSource.indexOf('aria-label="下载版本"')
  const wordIndex = editorSource.indexOf('onClick={handleDownloadWord}', versionIndex)
  const pdfIndex = editorSource.indexOf('onClick={handlePreparePdf}', wordIndex)
  const scoreIndexIndex = editorSource.indexOf('onClick={handleRegenerateScoreIndex}', pdfIndex)
  const regenerateIndex = editorSource.indexOf('onClick={handleRequestRegenerate}', scoreIndexIndex)
  const fullscreenIndex = editorSource.indexOf(
    'onClick={() => setTechnicalPreviewFullscreen((value) => !value)}',
    regenerateIndex,
  )

  assert.ok(versionIndex >= 0)
  assert.ok(versionIndex < wordIndex)
  assert.ok(wordIndex < pdfIndex)
  assert.ok(pdfIndex < scoreIndexIndex)
  assert.ok(scoreIndexIndex < regenerateIndex)
  assert.ok(regenerateIndex < fullscreenIndex)
})

test('重新生成索引按钮与重新生成正文同款次要样式，且在正文生成期间禁用', () => {
  assert.match(editorSource, /\{scoreIndexStarting \|\| scoreIndexRunning \? '重新生成中\.\.\.' : '重新生成索引'\}/)
  assert.match(
    editorSource,
    /onClick=\{handleRegenerateScoreIndex\}\s*\n\s*disabled=\{scoreIndexStarting \|\| scoreIndexRunning \|\| generationRunning\}\s*\n\s*icon="refresh"\s*\n\s*size="sm"\s*\n\s*variant="secondary"/,
  )
})

test('技术标导出工具栏移除编辑状态并缩短下载按钮文案', () => {
  assert.doesNotMatch(editorSource, /editorModeLabel/)
  assert.match(editorSource, /\{wordPreparing \? '生成中\.\.\.' : 'Word'\}/)
  assert.match(editorSource, /\{pdfPreparing \? '生成中\.\.\.' : 'PDF'\}/)
  assert.doesNotMatch(editorSource, /下载Word|下载PDF|OnlyOffice 在线编辑/)
})
