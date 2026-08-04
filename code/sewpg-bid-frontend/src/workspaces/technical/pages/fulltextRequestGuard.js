// 全文弹窗请求序号守卫：打开时自增取号、关闭时作废弃号，
// 慢响应落地前先校验序号仍有效，防止已关闭的弹窗被旧响应重新打开。
export const createFulltextRequestGuard = () => {
  let current = 0
  return {
    // 发起一次新请求并返回本次序号；新请求同时作废旧请求。
    begin: () => {
      current += 1
      return current
    },
    // 关闭弹窗时作废在途序号，使其响应不再落地。
    invalidate: () => {
      current += 1
    },
    isCurrent: (seq) => seq === current,
  }
}
