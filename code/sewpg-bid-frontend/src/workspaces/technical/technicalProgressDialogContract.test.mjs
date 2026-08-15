import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./components/TechnicalTaskProgressDialog.jsx', import.meta.url), 'utf8')
const generationSource = readFileSync(new URL('./components/TechnicalGenerationProgressModal.jsx', import.meta.url), 'utf8')
const indexSource = readFileSync(new URL('./components/TechnicalScoreIndexProgressModal.jsx', import.meta.url), 'utf8')
const outlineSource = readFileSync(new URL('./pages/TechnicalOutlineReview.jsx', import.meta.url), 'utf8')

test('统一进度弹窗使用加长的两段式布局', () => {
  assert.match(source, /<Dialog[^>]*size="md"/)
  assert.doesNotMatch(source, /DialogFooter/)
  assert.match(source, /<DialogHeader/)
  assert.match(source, /<DialogBody/)
})

test('右上角是文字关闭且关闭不触发停止', () => {
  assert.match(source, /onClick=\{onClose\}[\s\S]*?>关闭</)
  assert.doesNotMatch(source, /<DialogHeader[^>]*onClose=/)
  // DialogHeader 的标题块按内容收缩，不撑满就会把「关闭」挤到标题旁边而不是贴右
  assert.match(source, /<DialogHeader[^>]*\[&>div:first-child\]:flex-1/)
  assert.match(source, /<div className="flex w-full items-center justify-between gap-3">/)
})

test('运行中任务在主体右下角显示安静的停止按钮', () => {
  assert.match(source, /variant="dangerQuiet"/)
  assert.match(source, /onClick=\{onStop\}/)
  assert.match(source, /停止中|停止/)
  assert.match(source, /justify-end/)
})

test('四类技术标弹窗都接入统一进度弹窗壳', () => {
  assert.match(generationSource, /TechnicalTaskProgressDialog/)
  assert.match(indexSource, /TechnicalTaskProgressDialog/)
  assert.match(outlineSource, /TechnicalTaskProgressDialog/)
  assert.match(outlineSource, /TechnicalMaterialMatchProgressModal/)
  assert.doesNotMatch(outlineSource, /components\/shared\/MaterialMatchProgressModal/)
})
