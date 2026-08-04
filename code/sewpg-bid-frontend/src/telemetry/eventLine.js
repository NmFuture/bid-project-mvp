// 埋点归线工具：按事件自身 route 判定归属线，在入队时固化，flush 时按归线拆组上报
// 注意上报端点名为 technical/business，与 workspace slug（tech/business）不同，这里单独映射
// 带 .js 扩展名以便 node --test 直接解析（vite 两种写法都支持）
import { workspaceFromPathname } from '../utils/workspace.js'

// 商务路径（/workspace/business、/parse/business）→ business，其余统一 technical（与历史默认一致）
export const telemetryLineForRoute = (route) =>
  workspaceFromPathname(route) === 'business' ? 'business' : 'technical'

// flush 前按入队时固化的归线拆组；剥掉内部 line 字段，保持上报体字段不变
export const splitEventsByLine = (events) => {
  const groups = new Map()
  for (const item of events) {
    const line = item.line || 'technical'
    if (!groups.has(line)) groups.set(line, [])
    const { line: _line, ...payload } = item
    groups.get(line).push(payload)
  }
  return groups
}
