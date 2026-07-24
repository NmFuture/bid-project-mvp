import test from 'node:test'
import assert from 'node:assert/strict'

import { getOutlineDisplayNumber } from './outlineNumber.js'

test('uses tree sequence for outline review display instead of skill number', () => {
  assert.equal(getOutlineDisplayNumber({ tocNumber: '3.1' }, '6.2'), '6.2')
})

test('uses tree sequence when skill number is blank', () => {
  assert.equal(getOutlineDisplayNumber({ tocNumber: '' }, '6.2'), '6.2')
  assert.equal(getOutlineDisplayNumber({ tocNumber: null }, '6.2'), '6.2')
})

test('accepts legacy number aliases but keeps empty values hidden', () => {
  assert.equal(getOutlineDisplayNumber({ number: '一、' }), '一、')
  assert.equal(getOutlineDisplayNumber({ toc_number: '5.2' }), '5.2')
})
