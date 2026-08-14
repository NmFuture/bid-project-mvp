import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const pageSourceUrl = new URL('./TechnicalMaterialDB.jsx', import.meta.url)

test('素材库轮询解析附表同步状态并提供失败重试', async () => {
  const source = await readFile(pageSourceUrl, 'utf-8')

  assert.match(source, /technicalParseAssetSyncState/)
  assert.match(source, /detail\?\.technicalParseAssetSyncState/)
  assert.match(source, /technicalProjectsAPI\.retryParseAssetSync\(linkedProjectId\)/)
  assert.match(source, /catch[\s\S]*?window\.setTimeout\(poll,\s*\d+\)/)
  assert.match(source, /重试同步/)
  assert.match(source, /解析附表.*素材库/)
})
