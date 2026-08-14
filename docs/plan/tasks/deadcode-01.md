---
id: deadcode-01
scope: 后端 / 基础设施与通用
status: done
depends-on: []
---

# deadcode-01：删除 PeripheralStore 死代码

## objective

删除 `app/services/peripheral.py` 中的内存 `PeripheralStore` 类、单例与种子假数据；保留并收敛对外的 `PeripheralError`、`now_day` 等仍被引用的符号。

## context

- `docs/anbc_doc/架构总览/modules/peripheral.md`（已更新：替换完毕待删除）
- `docs/anbc_doc/架构总览/_data/common.json`
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/app/services/peripheral.py`
- `code/sewpg-bid-backend/tests/test_bid_material_scope_services.py`（:3312 有「新代码不再引用 peripheral_store」的断言，删除后需保留语义或调整）
- 同步更新 `docs/anbc_doc/架构总览/modules/peripheral.md` 行数与职责描述、`_data/common.json` loc

## 现状（2026-08-12 复核证据）

- `peripheral.py:74` 内存 `PeripheralStore`，`:1099` 单例 `peripheral_store`，文件共 1099 行且含种子假数据。
- 真实实现已就位：`material_store.py:54-57` `MaterialStore` 自述是 PeripheralStore raw/wiki 方法的 drop-in replacement，routes/services 均已改用 MaterialStore 系列。
- `peripheral_store` 全仓库（含测试）零真实调用方；外部模块从 peripheral.py 只 import `PeripheralError`/`now_day`。

## 改造方案

1. 全仓 grep `PeripheralStore`、`peripheral_store`，确认除自身与防回退断言外无引用。
2. 删除类、单例、种子数据；`peripheral.py` 收敛为统一异常 + 少量工具函数。
3. 调整 `test_bid_material_scope_services.py:3312` 的防回退断言（对象已不存在，改为断言模块不再导出该符号或直接移除用例）。

## verification

- 上述 pytest 命令跑 `tests/test_bid_material_scope_services.py` 及 import 了 peripheral 的相关测试文件。
- `grep -r "peripheral_store\|PeripheralStore" code/` 仅剩历史文档。
