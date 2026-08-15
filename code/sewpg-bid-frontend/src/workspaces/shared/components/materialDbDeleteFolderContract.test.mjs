import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// 工具栏「删除文件夹」按钮契约：handleDeleteFolder(path = selectedFolderPath) 的 path
// 是目录路径，直接写 onClick={handleDeleteFolder} 会把 React 事件对象当 path 传入，
// confirm 文案变成 [object ...] 且删除必然失败。这里锁定「调用时不传事件对象」。
test('素材库工具栏「删除文件夹」按钮不传事件对象、目录保护谓词照常生效', () => {
  const source = readFileSync(resolve(__dirname, 'MaterialDBPage.jsx'), 'utf8')

  // 按钮必须以无参方式调用，不能把 handler 引用直接绑给 onClick。
  assert.match(source, /onClick=\{\(\) => handleDeleteFolder\(\)\}/)
  assert.doesNotMatch(source, /onClick=\{handleDeleteFolder\}/)

  // handler 保持「无参时删除当前选中目录」的默认值语义，且仍走轨道注入的保护谓词。
  assert.match(source, /handleDeleteFolder = async \(path = selectedFolderPath\)/)
  assert.match(source, /!isFolderDeleteProtected\(targetPath\)/)
})
