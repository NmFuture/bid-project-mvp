import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  calculateWikiJobElapsedSeconds,
  formatWikiJobElapsed,
  resolveWikiJobElapsedTimestamp,
} from './technicalWikiJobProgress.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

test('Wiki 任务耗时优先使用 startedAt 并回退到 createdAt', () => {
  assert.equal(
    resolveWikiJobElapsedTimestamp({
      startedAt: '2026-07-30T10:00:05Z',
      createdAt: '2026-07-30T10:00:00Z',
    }),
    '2026-07-30T10:00:05Z',
  )
  assert.equal(
    resolveWikiJobElapsedTimestamp({ createdAt: '2026-07-30T10:00:00Z' }),
    '2026-07-30T10:00:00Z',
  )
  assert.equal(resolveWikiJobElapsedTimestamp({ startedAt: 'invalid' }), '')
})

test('Wiki 任务耗时计算与展示对非法值和未来时间安全回退', () => {
  const now = Date.parse('2026-07-30T10:02:05Z')

  assert.equal(calculateWikiJobElapsedSeconds('2026-07-30T10:00:00Z', now), 125)
  assert.equal(calculateWikiJobElapsedSeconds('2026-07-30T10:03:00Z', now), 0)
  assert.equal(calculateWikiJobElapsedSeconds('', now), 0)
  assert.equal(formatWikiJobElapsed(125), '2 分 5 秒')
  assert.equal(formatWikiJobElapsed('invalid'), '0 秒')
})

test('技术标 Wiki 使用 jobId 恢复轮询且不再调用无参数状态接口', () => {
  const source = readFileSync(resolve(__dirname, 'pages/TechnicalMaterialWiki.jsx'), 'utf8')

  // 锁定「带 jobId 调用」而非完整参数列表：8def749 起调用追加 { signal } 用于取消，
  // 无参数调用的禁用由下面 doesNotMatch 负责。
  assert.match(source, /bootstrapStatus\(wikiJobId/)
  assert.doesNotMatch(source, /bootstrapStatus\(\)/)
  assert.match(source, /readWikiJobStorage\(WIKI_JOB_ID_STORAGE_KEY\)/)
  // 405fdc1 起「已耗时」展示从本页移除（改由 MaterialPipelineProgress 分段进度呈现），
  // 不再锁定 resolveWikiJobElapsedTimestamp / calculateWikiJobElapsedSeconds 的调用点；
  // 这两个纯函数的行为由本文件前两个用例直接覆盖。
})
