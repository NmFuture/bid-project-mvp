import assert from 'node:assert/strict'
import test from 'node:test'

import { compareByName, sortFilesByName, sortNodesByName } from './materialSort.js'

test('中文按拼音首字母排序', () => {
  const names = ['载荷安全性评估报告', '部件校核报告', '风资源评估报告', '短名单']
  const sorted = [...names].sort(compareByName)
  assert.deepEqual(sorted, ['部件校核报告', '短名单', '风资源评估报告', '载荷安全性评估报告'])
})

test('数字按数值大小而非字符串序', () => {
  const sorted = ['第10章', '第2章', '第1章'].sort(compareByName)
  assert.deepEqual(sorted, ['第1章', '第2章', '第10章'])
})

test('机型编码的小数整体比数值，6.25 排在 6.7 前', () => {
  const sorted = ['EW6.7-202', 'EW10.0-220', 'EW6.25-202', 'EW5.0-202', 'EW6.25-220'].sort(compareByName)
  assert.deepEqual(sorted, ['EW5.0-202', 'EW6.25-202', 'EW6.25-220', 'EW6.7-202', 'EW10.0-220'])
})

test('同机型下后缀数字仍按数值排', () => {
  const sorted = ['WH6.25N-202', 'WH6.25N-182', 'WH6.25N-1000'].sort(compareByName)
  assert.deepEqual(sorted, ['WH6.25N-182', 'WH6.25N-202', 'WH6.25N-1000'])
})

test('目录排在文件前面，同类再按名称', () => {
  const sorted = sortNodesByName([
    { name: '乙文件.docx', children: [] },
    { name: '乙目录', children: [{ name: '子' }] },
    { name: '甲文件.docx', children: [] },
    { name: '甲目录', children: [{ name: '子' }] },
  ])
  assert.deepEqual(sorted.map((n) => n.name), ['甲目录', '乙目录', '甲文件.docx', '乙文件.docx'])
})

test('递归排序子层级且不改动原数组', () => {
  const input = [{ name: '根', children: [{ name: '乙' }, { name: '甲' }] }]
  const sorted = sortNodesByName(input)
  assert.deepEqual(sorted[0].children.map((n) => n.name), ['甲', '乙'])
  assert.deepEqual(input[0].children.map((n) => n.name), ['乙', '甲'])
})

test('文件列表排序兼容 title 字段与脏数据', () => {
  assert.deepEqual(sortFilesByName([{ title: 'B' }, { title: 'A' }]).map((f) => f.title), ['A', 'B'])
  assert.deepEqual(sortFilesByName(null), [])
})
