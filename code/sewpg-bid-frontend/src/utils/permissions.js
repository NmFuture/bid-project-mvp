// 角色权限工具：T 技术标 / B 商务标 / TB 标书统筹。

import { useMemo } from 'react'

export const ROLE = {
  T: 'T',
  B: 'B',
  TB: 'TB',
}

export const ROLE_LABEL = {
  T: '技术标专员',
  B: '商务标专员',
  TB: '标书统筹',
}

export const ROLE_DESC = {
  T: '负责技术标的解析、目录、缺口处理与正文撰写',
  B: '负责商务标的资格审查、业绩匹配、评分索引与附件映射',
  TB: '统筹技术标与商务标双线，含全局设置与审计权限',
}

const WORKSPACE_BY_ROLE = {
  T: ['tech'],
  B: ['business'],
  TB: ['tech', 'business'],
}

export const availableWorkspacesFor = (user) => {
  if (!user?.role) return []
  return WORKSPACE_BY_ROLE[user.role] || []
}

export const defaultWorkspaceFor = (user) => {
  const ws = availableWorkspacesFor(user)
  return ws[0] || 'tech'
}

export const canAccessWorkspace = (user, slug) => {
  if (!slug) return true
  return availableWorkspacesFor(user).includes(slug)
}

// TB 视图独有：可以在 UI 中横向并列展示双工作区
export const canViewBothWorkspaces = (user) => availableWorkspacesFor(user).length > 1

// 设置/审计写权限：仅 TB
export const canWriteSettings = (user) => user?.role === ROLE.TB
export const canViewGlobalAudit = (user) => user?.role === ROLE.TB

// 角色 → 工作台路由（保留参数位以备将来按角色定制）
export const dashboardPathFor = () => '/dashboard'

// hooks
export const useCurrentRole = (user) => useMemo(() => user?.role || null, [user])

export const useAvailableWorkspaces = (user) =>
  useMemo(() => availableWorkspacesFor(user), [user])
