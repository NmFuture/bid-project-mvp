import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeBidType,
  parseRouteFromBidType,
  projectRoute,
  slugFromBidType,
  workspaceRoute,
} from './workspace.js'

test('workspace bid type helpers require an explicit known bid type', () => {
  assert.equal(normalizeBidType(''), '')
  assert.equal(normalizeBidType('unknown'), '')
  assert.equal(slugFromBidType(''), '')
  assert.equal(slugFromBidType('unknown'), '')
  assert.equal(parseRouteFromBidType(''), '')
  assert.equal(parseRouteFromBidType('unknown'), '')
})

test('workspace bid type helpers resolve explicit bid types', () => {
  assert.equal(normalizeBidType('商务响应文件'), '商务标')
  assert.equal(normalizeBidType('技术方案'), '技术标')
  assert.equal(slugFromBidType('商务标'), 'business')
  assert.equal(slugFromBidType('技术标'), 'tech')
  assert.equal(parseRouteFromBidType('商务标', 'P-1'), '/parse/business?projectId=P-1')
  assert.equal(parseRouteFromBidType('技术标', 'P-1'), '/parse/technical?projectId=P-1')
})

test('invalid workspace slugs do not emit legacy root project paths', () => {
  assert.equal(workspaceRoute('', '/projects/P-1'), '/')
  assert.equal(workspaceRoute('unknown', '/materials/raw'), '/')
  assert.equal(projectRoute('P-1', '/outline', ''), '/')
  assert.equal(projectRoute('P-1', '/outline', 'tech'), '/workspace/tech/projects/P-1/outline')
})
