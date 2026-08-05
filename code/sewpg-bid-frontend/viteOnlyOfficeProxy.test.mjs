import test from 'node:test'
import assert from 'node:assert/strict'

import createViteConfig from './vite.config.js'

test('OnlyOffice 开发代理保留浏览器端口并转发缓存文件', () => {
  const config = createViteConfig({ mode: 'test' })
  const dsProxy = config.server.proxy['/ds']
  const cacheProxy = config.server.proxy['/cache']

  assert.equal(dsProxy.changeOrigin, false)
  assert.equal(cacheProxy.changeOrigin, false)
  assert.equal(cacheProxy.target, dsProxy.target)
})
