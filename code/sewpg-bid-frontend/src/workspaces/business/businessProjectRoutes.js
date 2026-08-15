// 实现已合并到 shared/utils/projectRoutes.js（两侧归一化后完全相同），
// 这里只保留商务标命名的薄壳，页面与测试的 import 不变。
import {
  createProjectParseResultRoutes,
  selectParseProjectId,
  shouldSyncProjectParseResultRoute,
} from '../shared/utils/projectRoutes.js'

const {
  projectParseResultRoute,
  projectParseResultMenuRoute,
  projectParseResultNavigation,
} = createProjectParseResultRoutes('/parse/business')

export const businessProjectParseResultRoute = projectParseResultRoute
export const businessProjectParseResultMenuRoute = projectParseResultMenuRoute
export const businessProjectParseResultNavigation = projectParseResultNavigation

export const selectBusinessParseProjectId = selectParseProjectId
export const shouldSyncBusinessProjectParseResultRoute = shouldSyncProjectParseResultRoute
