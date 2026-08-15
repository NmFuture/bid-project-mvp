// 实现已合并到 shared/utils/projectRoutes.js（两侧归一化后完全相同），
// 这里只保留技术标命名的薄壳，页面与测试的 import 不变。
import {
  createProjectParseResultRoutes,
  selectParseProjectId,
  shouldSyncProjectParseResultRoute,
} from '../shared/utils/projectRoutes.js'

const {
  projectParseResultRoute,
  projectParseResultMenuRoute,
  projectParseResultNavigation,
} = createProjectParseResultRoutes('/parse/technical')

export const technicalProjectParseResultRoute = projectParseResultRoute
export const technicalProjectParseResultMenuRoute = projectParseResultMenuRoute
export const technicalProjectParseResultNavigation = projectParseResultNavigation

export const selectTechnicalParseProjectId = selectParseProjectId
export const shouldSyncTechnicalProjectParseResultRoute = shouldSyncProjectParseResultRoute
