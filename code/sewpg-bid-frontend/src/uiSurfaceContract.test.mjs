import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = (path) => readFile(new URL(path, import.meta.url), 'utf8')

const [
  dashboardSource,
  jobMonitorSource,
  settingsSource,
  technicalProjectListSource,
  businessProjectListSource,
  technicalTenderReviewSource,
  businessTenderReviewSource,
  technicalStageProgressSource,
  businessStageProgressSource,
  technicalStageLayoutSource,
  businessStageLayoutSource,
  indexCssSource,
] = await Promise.all([
  readSource('./pages/Dashboard.jsx'),
  readSource('./pages/JobMonitor.jsx'),
  readSource('./pages/Settings.jsx'),
  readSource('./workspaces/technical/pages/TechnicalProjectList.jsx'),
  readSource('./workspaces/business/pages/BusinessProjectList.jsx'),
  readSource('./workspaces/technical/pages/TechnicalTenderReview.jsx'),
  readSource('./workspaces/business/pages/BusinessTenderReview.jsx'),
  readSource('./workspaces/technical/components/TechnicalProjectStageProgress.jsx'),
  readSource('./workspaces/business/components/BusinessProjectStageProgress.jsx'),
  readSource('./workspaces/technical/components/TechnicalProjectStageLayout.jsx'),
  readSource('./workspaces/business/components/BusinessProjectStageLayout.jsx'),
  readSource('./index.css'),
])

const assertAllPageHeadersUsePanel = (source, pageName) => {
  const pageHeaderCount = source.match(/<PageHeader\b/g)?.length || 0
  const panelVariantCount = source.match(/variant="panel"/g)?.length || 0

  assert.ok(pageHeaderCount > 0, `${pageName} 应使用 PageHeader`)
  assert.equal(panelVariantCount, pageHeaderCount, `${pageName} 的 PageHeader 应统一使用 panel 变体`)
}

const compactUploadBranch = (source, flag) => {
  const branch = source.match(new RegExp(`if \\(${flag}\\) \\{([\\s\\S]*?)\\n  \\}\\n\\n  return \\(`))?.[1]
  assert.ok(branch, `应保留 ${flag} 未完成解析分支`)
  return branch
}

test('工作台移除待办与活动模块并过滤待处理指标', () => {
  assert.doesNotMatch(dashboardSource, /今日待办|最近活动/)

  const metricsFilter = dashboardSource.match(/const metrics = .*\.filter\([^\n]+/)
  assert.ok(metricsFilter, '工作台应保留指标过滤契约')
  assert.match(metricsFilter[0], /['"]todo['"]/, '工作台指标过滤应排除 key=todo')
  assert.match(metricsFilter[0], /metric\.key/, '工作台指标应按稳定 key 过滤')
})

test('项目总览与耗时监控使用统一的方形标题面板', () => {
  assertAllPageHeadersUsePanel(technicalProjectListSource, '技术标项目总览')
  assertAllPageHeadersUsePanel(businessProjectListSource, '商务标项目总览')
  assertAllPageHeadersUsePanel(jobMonitorSource, '耗时监控')
})

test('系统设置使用统一标题面板', () => {
  assertAllPageHeadersUsePanel(settingsSource, '系统设置')
  assert.doesNotMatch(
    settingsSource,
    /<PageHeader\s+className="[^"]*\bborder-b\b[^"]*"/,
    '系统设置标题不应继续使用裸分隔线',
  )
})

test('耗时监控指标使用标准字号并与加载布局保持一致', () => {
  const metricValueClasses = jobMonitorSource.match(
    /<span className="([^"]+)">\s*\{metric\.value\}\s*<\/span>/,
  )?.[1]

  assert.ok(metricValueClasses, '应能定位耗时指标数值样式')
  assert.match(metricValueClasses, /(?:^|\s)text-xl(?:\s|$)/)
  assert.doesNotMatch(metricValueClasses, /(?:^|\s)(?:sm:|md:|lg:|xl:)?text-(?:2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl|\[[^\]]+\])(?:\s|$)/)
  assert.match(jobMonitorSource, /grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4/)
  assert.match(jobMonitorSource, /h-\[76px\]/)
})

test('技术标与商务标解析页统一使用标题面板', () => {
  assertAllPageHeadersUsePanel(technicalTenderReviewSource, '技术标解析页')
  assertAllPageHeadersUsePanel(businessTenderReviewSource, '商务标解析页')
})

test('解析未完成分支不再收缩为 760px 居中卡片', () => {
  const technicalCompactUpload = compactUploadBranch(
    technicalTenderReviewSource,
    'showTechnicalCompactUpload',
  )
  const businessCompactUpload = compactUploadBranch(
    businessTenderReviewSource,
    'showBusinessCompactUpload',
  )

  assert.doesNotMatch(technicalCompactUpload, /max-w-\[760px\]/)
  assert.doesNotMatch(businessCompactUpload, /max-w-\[760px\]/)
  assert.match(technicalCompactUpload, /<PageHeader\s+[\s\S]*?variant="panel"/)
  assert.match(businessCompactUpload, /<PageHeader\s+[\s\S]*?variant="panel"/)
})

test('项目阶段切换保留进度快照且不重复淡入', () => {
  for (const [name, source] of [
    ['技术标', technicalStageProgressSource],
    ['商务标', businessStageProgressSource],
  ]) {
    assert.match(source, /StageCache = new Map\(\)/, `${name}应按项目缓存阶段快照`)
    assert.match(source, /useState\(cachedStages\)/, `${name}应使用缓存快照初始渲染`)
    assert.match(source, /if \(cached\.length\) \{[\s\S]*?setLoading\(false\)/, `${name}后台刷新时不应切换为加载条`)
    assert.match(source, /StagesAPI\.list\(projectId\)/, `${name}仍应后台请求最新阶段`)
  }

  for (const [name, source] of [
    ['技术标', technicalStageLayoutSource],
    ['商务标', businessStageLayoutSource],
  ]) {
    assert.match(source, /<(?:Technical|Business)ProjectStageProgress[\s\S]*?<Outlet\s*\/>/, `${name}应在父级路由持久渲染进度条`)
    assert.match(source, /refreshKey=\{location\.pathname\}/, `${name}应在子路由变化时后台刷新阶段`)
  }

  assert.match(
    indexCssSource,
    /\.stage-page\.animate-fade-in\s*\{\s*animation:\s*none;/,
    '项目阶段页不应在每次路由切换时整页淡入',
  )
})
