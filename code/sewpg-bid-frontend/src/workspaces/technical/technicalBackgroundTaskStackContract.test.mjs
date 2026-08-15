import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const stackSource = readFileSync(new URL('./components/TechnicalBackgroundTaskStack.jsx', import.meta.url), 'utf8')
const definitionsSource = readFileSync(new URL('./technicalBackgroundTaskDefinitions.js', import.meta.url), 'utf8')
const tasksSource = readFileSync(new URL('./technicalBackgroundTasks.js', import.meta.url), 'utf8')
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

test('只有完成任务强制显示百分之百，停止和失败保留真实进度', () => {
  assert.match(
    stackSource,
    /status\s*===\s*['"]completed['"]\s*\?\s*100\s*:\s*clampPercentage\(displayed\)/,
  )
  assert.doesNotMatch(stackSource, /TERMINAL_STATUSES\.has\(status\)\s*\?\s*100/)
})

test('首次正文和重新生成正文合并为一条任务，按发起页回跳', () => {
  // 后端是同一个 fill-generation 任务，登记两种类型会让同一件事出现两张卡
  assert.doesNotMatch(definitionsSource, /body-regenerate/)
  assert.match(definitionsSource, /'body-generate':/)
  assert.match(definitionsSource, /route:\s*\(\{ projectId, page \}\) => projectRoute\(projectId, page \|\| 'gaps'\)/)
})

test('超过三条时提示另有 N 个任务', () => {
  assert.match(stackSource, /const visibleTasks = backgroundTasks\.slice\(0,\s*3\)/)
  assert.match(stackSource, /const overflowCount = backgroundTasks\.length - visibleTasks\.length/)
  assert.match(stackSource, /另有 \{overflowCount\} 个任务/)
})

test('终态通知点击查看或主动关闭后消失，运行中任务不提供关闭', () => {
  assert.match(stackSource, /clearTechnicalTask/)
  const consumeStart = stackSource.indexOf('const consumeTerminalTask')
  const consumeEnd = stackSource.indexOf('const visibleTasks', consumeStart)
  const consumeSource = stackSource.slice(consumeStart, consumeEnd)
  assert.ok(consumeStart >= 0)
  // 运行中的任务不能被顺手清掉，否则前端就丢了追踪
  assert.match(consumeSource, /if \(technicalTaskIsActive\(task\)\) return/)
  assert.match(consumeSource, /clearTechnicalTask\(task\.taskType, task\.projectId\)/)

  assert.match(stackSource, /consumeTerminalTask\(task\)\s*\n\s*navigate\(technicalTaskRoute\(task\)\)/)
  assert.match(stackSource, /active \? null : \([\s\S]*?onClick=\{\(\) => consumeTerminalTask\(task\)\}/)
  // 后台卡片不提供停止，避免误触
  assert.doesNotMatch(stackSource, /停止中|onStop/)
})

test('后端查无任务时清理登记，其余查询失败保留上一次进度', () => {
  assert.match(stackSource, /if \(error\?\.status === 404\) \{[\s\S]*?clearTechnicalTask\(task\.taskType, task\.projectId\)/)
  const catchStart = stackSource.indexOf('} catch (error) {')
  const catchEnd = stackSource.indexOf('const status =', catchStart)
  assert.match(stackSource.slice(catchStart, catchEnd), /\n\s+return\n/)
})

test('后端说任务是 idle 或没状态时清掉登记，不冒充成已完成通知', () => {
  assert.match(
    stackSource,
    /if \(!technicalTaskIsActive\(\{ status \}\) && !TECHNICAL_TASK_NOTIFIABLE_STATUSES\.has\(status\)\) \{[\s\S]*?clearTechnicalTask\(task\.taskType, task\.projectId\)/,
  )
  // 已经写进登记表的 idle 记录也要在读取时被剔掉，否则永远轮不到上面那段
  assert.match(tasksSource, /export const TECHNICAL_TASK_NOTIFIABLE_STATUSES = new Set\(\['completed', 'failed', 'error', 'cancelled', 'stale'\]\)/)
  assert.match(tasksSource, /if \(!technicalTaskIsTrackable\(task\)\) return false/)
})

test('已停止任务使用中性停止图标和文案', () => {
  assert.match(stackSource, /const cancelled = task\.status === ['"]cancelled['"]/)
  assert.match(stackSource, /cancelled\s*\?\s*['"]text-outline['"]/)
  assert.match(stackSource, /cancelled\s*\?\s*['"]stop_circle['"]/)
  assert.match(stackSource, /cancelled\s*\?\s*['"]任务已停止['"]/)
})
