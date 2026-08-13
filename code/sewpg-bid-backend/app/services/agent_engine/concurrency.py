"""全局 Agent 并发预算（改造方案 §6 波次 B4 / harness-02，engine-06 落地）。

单一事实：进程级只有一个 `AGENT_CONCURRENCY_BUDGET`。历史三套互不知晓的
信号量池（引擎默认请求槽、S1 分片槽、目录章节槽）改为从它派生的
`BudgetPool`：总并发恒 ≤ 预算，各池只保留自己的上限（cap），
消除「实际并发=各池之和」的叠加超发。

进程型引擎（codex/pi，一个 session 一个进程）同样从本预算取槽：
一个许可 = 一个并发会话进程（方案 §7：进程池上限并入本预算，不再单设）。

原语选 threading（跨线程/跨事件循环安全）：引擎实例会被 asyncio.run 桥接的
工作线程与 FastAPI 事件循环复用，asyncio.Semaphore 有循环亲和性，跨循环
复用会炸（engine-03 的取舍，本模块沿用）。
"""
from __future__ import annotations

import threading

from app.core.config import settings


class ConcurrencyBudget:
    """进程级并发预算总量。各用池处用 `derive` 派生池，不直接操作本类。"""

    def __init__(self, total: int) -> None:
        self._total = max(1, int(total))
        self._slots = threading.BoundedSemaphore(self._total)

    @property
    def total(self) -> int:
        return self._total

    def derive(self, cap: int | None = None) -> "BudgetPool":
        """派生一个池：cap=None 可用满整个预算，否则在预算内再限 cap。"""
        return BudgetPool(self, cap)

    # BudgetPool 内部接口（模块内协作，不算公开 API）。
    def acquire_permit(self, blocking: bool = True) -> bool:
        return self._slots.acquire(blocking)

    def release_permit(self) -> None:
        self._slots.release()


class BudgetPool:
    """从全局预算派生的并发池；接口对齐 threading.BoundedSemaphore
    （`acquire(blocking=False)` / `release`），引擎 `_request_slot` 的
    非阻塞轮询与取消不泄漏语义（engine-03 F1）保持不变。

    获取顺序恒为 预算许可 → 自身上限：非阻塞获取在第二步失败时立即归还
    预算许可，不占坑、无循环等待（两个方向都不会死锁）。
    """

    def __init__(self, budget: ConcurrencyBudget, cap: int | None = None) -> None:
        self._budget = budget
        self._cap = None if cap is None else max(1, min(int(cap), budget.total))
        self._cap_slots = None if self._cap is None else threading.BoundedSemaphore(self._cap)

    @property
    def budget(self) -> ConcurrencyBudget:
        return self._budget

    @property
    def cap(self) -> int:
        """本池在预算内的实际上限（cap=None 即预算总量）。"""
        return self._budget.total if self._cap is None else self._cap

    def acquire(self, blocking: bool = True) -> bool:  # noqa: FBT001,FBT002 - 对齐 threading.Semaphore 接口
        if not blocking:
            if not self._budget.acquire_permit(blocking=False):
                return False
            if self._cap_slots is not None and not self._cap_slots.acquire(blocking=False):
                self._budget.release_permit()  # 上限已满：预算许可立即归还
                return False
            return True
        self._budget.acquire_permit()
        if self._cap_slots is not None:
            self._cap_slots.acquire()
        return True

    def release(self) -> None:
        if self._cap_slots is not None:
            self._cap_slots.release()
        self._budget.release_permit()


# 进程级单例：取值在 import 时从 settings 快照（与既有模块级槽位池同一模式）。
AGENT_CONCURRENCY_BUDGET = ConcurrencyBudget(settings.agent_concurrency_budget)
