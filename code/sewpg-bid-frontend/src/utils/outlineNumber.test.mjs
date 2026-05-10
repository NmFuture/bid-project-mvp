import test from 'node:test'
import assert from 'node:assert/strict'

import { getOutlineDisplayNumber } from './outlineNumber.js'

test('uses skill tocNumber for outline review display instead of generated sequence', () => {
  assert.equal(getOutlineDisplayNumber({ tocNumber: '3.1' }, '6.2'), '3.1')
})

test('does not fall back to generated sequence when skill number is blank', () => {
  assert.equal(getOutlineDisplayNumber({ tocNumber: '' }, '6.2'), '')
  assert.equal(getOutlineDisplayNumber({ tocNumber: null }, '6.2'), '')
})

test('accepts legacy number aliases but keeps empty values hidden', () => {
  assert.equal(getOutlineDisplayNumber({ number: '一、' }, '1'), '一、')
  assert.equal(getOutlineDisplayNumber({ toc_number: '5.2' }, '6.2'), '5.2')
})
