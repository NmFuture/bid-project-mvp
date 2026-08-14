import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const stackSource = readFileSync(new URL('./components/TechnicalBackgroundTaskStack.jsx', import.meta.url), 'utf8')
const definitionsSource = readFileSync(new URL('./technicalBackgroundTaskDefinitions.js', import.meta.url), 'utf8')
const shellSource = readFileSync(new URL('../../components/layout/AppShell.jsx', import.meta.url), 'utf8')
const parseBannerSource = readFileSync(new URL('../../components/layout/ParseRunningBanner.jsx', import.meta.url), 'utf8')

test('右下角任务栈最多显示三条且文字顺序固定', () => {
  assert.match(stackSource, /slice\(0,\s*3\)/)
  assert.match(
    stackSource,
    /task\.taskName[\s\S]*?task\.percentage[\s\S]*?task\.projectName/,
  )
})

test('任务卡片点击回到带恢复参数的任务页面', () => {
  assert.match(stackSource, /navigate\(technicalTaskRoute\(task\)\)/)
  assert.match(definitionsSource, /progressTask/)
})

test('AppShell 挂载技术标任务栈且旧提示条只处理商务标', () => {
  assert.match(shellSource, /<TechnicalBackgroundTaskStack\s*\/>/)
  assert.match(parseBannerSource, /bidType\s*===\s*['"]business['"]/)
})
