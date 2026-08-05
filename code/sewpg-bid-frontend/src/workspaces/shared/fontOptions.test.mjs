import test from 'node:test'
import assert from 'node:assert/strict'

import { DOCUMENT_FONT_OPTIONS } from './fontOptions.js'

test('文档字体选项使用对外正式字体名', () => {
  assert.deepEqual(DOCUMENT_FONT_OPTIONS, {
    zh: [
      { value: '等线', label: '等线' },
      { value: '等线 Light', label: '等线 Light' },
      { value: '宋体', label: '宋体' },
    ],
    en: [
      { value: 'Times New Roman', label: 'Times New Roman' },
      { value: 'Arial', label: 'Arial' },
    ],
  })
})
