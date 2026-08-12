"""回归：technical_gap_service 的兜底 except 分支依赖模块级 logger。

缺陷背景：`283381f` 引入「素材匹配后自动构建事实表」，其 except 分支调用
`logger.exception(...)`，但该模块从未定义 logger。结果本应被吞掉的可恢复失败
抛出 NameError 逃逸 except，把整个 gaps-detection 请求打成 HTTP 500。

这类"异常处理里的异常"不会在正常路径暴露，只在触发兜底分支时炸，因此用
静态断言锁住：模块必须具备可用的 logger。
"""

import logging

from app.services import technical_gap_service as gap_service


def test_module_exposes_usable_logger():
    logger = getattr(gap_service, "logger", None)
    assert logger is not None, "technical_gap_service 必须定义模块级 logger"
    assert isinstance(logger, logging.Logger)


def test_logger_exception_in_fallback_does_not_raise(caplog):
    """模拟兜底分支：logger.exception 必须能安全调用，不得抛 NameError。"""
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError("boom")
        except Exception:
            gap_service.logger.exception("项目 %s 自动建表失败", "PRJ-TEST")
    assert any("PRJ-TEST" in rec.getMessage() for rec in caplog.records)
