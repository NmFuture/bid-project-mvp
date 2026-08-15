import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

test('技术标 Wiki 使用 jobId 恢复轮询且不再调用无参数状态接口', () => {
  const source = readFileSync(resolve(__dirname, 'pages/TechnicalMaterialWiki.jsx'), 'utf8')

  // 锁定「带 jobId 调用」而非完整参数列表：8def749 起调用追加 { signal } 用于取消，
  // 无参数调用的禁用由下面 doesNotMatch 负责。
  assert.match(source, /bootstrapStatus\(wikiJobId/)
  assert.doesNotMatch(source, /bootstrapStatus\(\)/)
  assert.match(source, /readWikiJobStorage\(WIKI_JOB_ID_STORAGE_KEY\)/)
  // 405fdc1 起「已耗时」展示从本页移除（改由 MaterialPipelineProgress 分段进度呈现），
  // 耗时计算纯函数随 technicalWikiJobProgress.js 一并删除。
})
