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
