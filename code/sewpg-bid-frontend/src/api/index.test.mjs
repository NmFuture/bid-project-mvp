import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const apiSourceUrl = new URL('./index.js', import.meta.url)

test('parse API exposes backend cancel endpoints', async () => {
  const source = await readFile(apiSourceUrl, 'utf-8')

  assert.match(
    source,
    /cancel:\s*\(projectId\)\s*=>\s*request\(`\/technical\/projects\/\$\{projectId\}\/parse-results\/cancel`,\s*\{\s*method:\s*'POST'/s,
  )
  assert.match(
    source,
    /cancel:\s*\(projectId\)\s*=>\s*request\(`\/business\/projects\/\$\{projectId\}\/parse-results\/cancel`,\s*\{\s*method:\s*'POST'/s,
  )
})

test('技术标项目更新为附件同步预留足够等待时间', async () => {
  const source = await readFile(apiSourceUrl, 'utf-8')

  assert.match(
    source,
    /technicalProjectsAPI\s*=\s*\{[\s\S]*?update:\s*\(id, data\)\s*=>\s*request\(`\/technical\/projects\/\$\{id\}`,\s*\{\s*method:\s*'PUT',\s*body:\s*data,\s*timeoutMs:\s*5\s*\*\s*60\s*\*\s*1000,\s*retryCount:\s*0,?\s*\}\)/,
  )
})

test('技术标和商务标项目删除为素材清理预留足够等待时间', async () => {
  const source = await readFile(apiSourceUrl, 'utf-8')

  assert.match(
    source,
    /technicalProjectsAPI\s*=\s*\{[\s\S]*?delete:\s*\(id\)\s*=>\s*request\(`\/technical\/projects\/\$\{id\}`,\s*\{\s*method:\s*'DELETE',\s*timeoutMs:\s*5\s*\*\s*60\s*\*\s*1000,\s*retryCount:\s*0,?\s*\}\)/,
  )
  assert.match(
    source,
    /businessProjectsAPI\s*=\s*\{[\s\S]*?delete:\s*\(id\)\s*=>\s*request\(`\/business\/projects\/\$\{id\}`,\s*\{\s*method:\s*'DELETE',\s*timeoutMs:\s*5\s*\*\s*60\s*\*\s*1000,\s*retryCount:\s*0,?\s*\}\)/,
  )
})
