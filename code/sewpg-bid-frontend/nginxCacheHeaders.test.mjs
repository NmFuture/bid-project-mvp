import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const nginxConf = readFileSync(join(here, 'nginx.conf'), 'utf8')

const locationBlock = (path) => {
  const escapedPath = path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = nginxConf.match(new RegExp(`location ${escapedPath} \\{([\\s\\S]*?)\\n  \\}`))
  return match?.[1] || ''
}

test('SPA route fallback is not cached so parsed pages do not run stale bundles', () => {
  const rootLocation = locationBlock('/')

  assert.match(rootLocation, /try_files\s+\$uri\s+\$uri\/\s+\/index\.html;/)
  assert.match(rootLocation, /Cache-Control\s+"no-store,\s*no-cache,\s*must-revalidate,\s*proxy-revalidate"/)
  assert.match(rootLocation, /Pragma\s+"no-cache"/)
  assert.match(rootLocation, /Expires\s+"0"/)
})

test('hashed Vite assets can still use immutable caching', () => {
  const assetsLocation = locationBlock('/assets/')

  assert.match(assetsLocation, /try_files\s+\$uri\s+=404;/)
  assert.match(assetsLocation, /Cache-Control\s+"public,\s*max-age=31536000,\s*immutable"/)
})
