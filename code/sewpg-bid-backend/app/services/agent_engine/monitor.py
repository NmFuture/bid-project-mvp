"""引擎无关的会话监管器（改造方案 §5）：idle 超时 / 心跳 / 进度活动时钟。

三引擎事件源不同（opencode HTTP 轮询 / codex exec JSONL / pi RPC 事件流），
监管语义同构：新输出重置 idle 时钟，静默超 `idle_timeout` 判停滞，静默期按
`heartbeat_interval` 发进度心跳。差异点（超时时长、心跳间隔）经构造参数注入，
判定语义差异经方法选择注入（见 `SessionMonitor` 方法注释）；断线重连耗时经
`apply_disconnect` 加回时钟（断线时间不计入 idle，服务重启 ≠ 模型 stall，
opencode 轮询专有语义，本地子进程引擎不调用即可）。
"""
from __future__ import annotations

import time
from typing import Callable


class SessionMonitor:
    """一次会话运行的监管时钟（idle / heartbeat / elapsed）。

    只管时钟与判定，不碰引擎 IO：到期后怎么办（发心跳载荷、停会话、杀进程、
    报错文案）由各引擎决定；进度签名去重留在引擎侧（签名形态各异）。

    - `note_event`：任意引擎事件，只重置 idle 时钟（codex/pi 的事件流；
      codex 心跳只按自身间隔走、不被活动复位，故 codex 只用本方法）。
    - `note_progress`：有新进度输出，idle 与心跳时钟一起复位（opencode/pi
      的进度增量语义）。
    - `is_idle_timeout` / `deadline`：停滞判定（前者为相对判定，后者供
      宽限/收敛等待循环作循环条件）。
    - `heartbeat_due` / `take_heartbeat`：心跳到期判定与序号（1 起）。
    """

    def __init__(self, *, idle_timeout: float, heartbeat_interval: float) -> None:
        self.idle_timeout = float(idle_timeout)
        self.heartbeat_interval = float(heartbeat_interval)
        now = time.monotonic()
        self.started_at = now
        self.last_activity = now
        self.last_heartbeat = now
        self.heartbeat_index = 0

    def note_event(self) -> None:
        """任意引擎事件：只重置 idle 时钟（心跳时钟不动）。"""
        self.last_activity = time.monotonic()

    def note_progress(self) -> None:
        """有新进度输出：idle 与心跳时钟一起复位（心跳序号清零）。"""
        self.last_activity = time.monotonic()
        self.last_heartbeat = self.last_activity
        self.heartbeat_index = 0

    def apply_disconnect(self, disconnected: float) -> None:
        """断线重连耗时加回活动/心跳时钟：断线时间不计入 idle。"""
        if disconnected > 0:
            self.last_activity += disconnected
            self.last_heartbeat += disconnected

    def is_idle_timeout(self) -> bool:
        """停滞判定：距上次活动超过 idle_timeout。"""
        return time.monotonic() - self.last_activity > self.idle_timeout

    def deadline(self) -> float:
        """idle 停摆的绝对时刻（`time.monotonic() < deadline` 作等待循环条件）。"""
        return self.last_activity + self.idle_timeout

    def heartbeat_due(self) -> bool:
        """心跳到期判定：距上次心跳（或活动复位）达到 heartbeat_interval。"""
        return time.monotonic() - self.last_heartbeat >= self.heartbeat_interval

    def take_heartbeat(self) -> int:
        """记一次心跳并返回心跳序号（1 起），同时复位心跳时钟。"""
        self.heartbeat_index += 1
        self.last_heartbeat = time.monotonic()
        return self.heartbeat_index

    def idle_seconds(self) -> float:
        """距上次活动的秒数（心跳载荷 idleSeconds 用）。"""
        return time.monotonic() - self.last_activity

    def elapsed_seconds(self) -> float:
        """距监管开始的秒数（进度回执 elapsedSeconds 用）。"""
        return time.monotonic() - self.started_at

    def idle_remaining(self) -> float:
        """距 idle 停摆的剩余秒数（等待粒度跟随监管 deadline 用）。"""
        return self.deadline() - time.monotonic()

    def heartbeat_remaining(self) -> float:
        """距下次心跳到期的剩余秒数。"""
        return self.last_heartbeat + self.heartbeat_interval - time.monotonic()

    @staticmethod
    def should_cancel(cancel_check: Callable[[], bool] | None) -> bool:
        """取消判定（None = 未挂取消监管）。"""
        return cancel_check is not None and cancel_check()
