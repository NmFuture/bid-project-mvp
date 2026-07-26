from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings as settings_module
from app.models.materials import SystemConfig, TemplateAsset
from app.services import system_settings as system_settings_module
from app.services.peripheral import PeripheralError
from app.services.system_settings import (
    ensure_template_type_allowed,
    system_settings_service,
    template_types_for_user,
)


def _run(coro):
    return asyncio.run(coro)


def _template(template_id: int, template_type: str, *, is_active: bool = True) -> TemplateAsset:
    asset = TemplateAsset(
        id=template_id,
        asset_type="default_template",
        table_key=template_type,
        file_name=f"{template_type}-模板.docx",
        version="2026.07",
        minio_key=f"templates/default/{template_type}/demo.docx",
        minio_bucket="bid-templates",
        size_bytes=128,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        is_active=is_active,
        uploaded_by="测试用户",
    )
    asset.created_at = datetime(2026, 7, 22, 10, 0, 0)
    return asset


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, results):
        self._results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, _query):
        return self._results.pop(0)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def delete(self, _obj):
        return None

    def add(self, _obj):
        return None


def _patch_db(results):
    """替换 _ensure_tables 与 async_session，按顺序消费预置的查询结果。"""
    return (
        patch.object(system_settings_service, "_ensure_tables", new=AsyncMock()),
        patch.object(system_settings_module, "async_session", side_effect=lambda: _FakeSession(results)),
    )


def _llm_config(**overrides):
    config = {
        "enabled": True,
        "providerId": "mimo",
        "baseUrl": "https://llm.example.com/v1",
        "apiKey": "sk-test",
        "model": "demo-model",
        "modelId": "demo-model",
    }
    config.update(overrides)
    return config


# ===== 角色 -> 模板类型口径 =====

def test_template_types_for_user_role_mapping() -> None:
    assert template_types_for_user({"role": "T"}) == {"technical"}
    assert template_types_for_user({"role": "B"}) == {"business"}
    assert template_types_for_user({"role": "TB"}) == {"technical", "business"}


def test_template_types_for_user_without_role_is_unfiltered() -> None:
    assert template_types_for_user(None) is None
    assert template_types_for_user({}) is None
    assert template_types_for_user({"role": ""}) is None
    assert template_types_for_user({"role": "member"}) is None


def test_ensure_template_type_allowed_raises_403_for_mismatched_role() -> None:
    with pytest.raises(PeripheralError) as exc_info:
        ensure_template_type_allowed("business", {"role": "T"})
    assert exc_info.value.status_code == 403
    with pytest.raises(PeripheralError) as exc_info:
        ensure_template_type_allowed("technical", {"role": "B"})
    assert exc_info.value.status_code == 403


def test_ensure_template_type_allowed_accepts_matching_or_unknown_role() -> None:
    ensure_template_type_allowed("technical", {"role": "T"})
    ensure_template_type_allowed("business", {"role": "B"})
    ensure_template_type_allowed("technical", {"role": "TB"})
    ensure_template_type_allowed("business", {"role": "TB"})
    ensure_template_type_allowed("business", None)
    ensure_template_type_allowed("technical", {"role": "member"})


# ===== default_templates_list 角色过滤 =====

def test_default_templates_list_filters_by_role() -> None:
    rows = [_template(1, "technical"), _template(2, "business")]
    ensure_patch, session_patch = _patch_db([_FakeResult(rows)])
    with ensure_patch, session_patch:
        payload = _run(system_settings_service.default_templates_list(user={"role": "T"}))
    assert [item["templateType"] for item in payload["items"]] == ["technical"]
    assert payload["templateTypes"] == [{"key": "technical", "label": "技术标"}]

    rows = [_template(1, "technical"), _template(2, "business")]
    ensure_patch, session_patch = _patch_db([_FakeResult(rows)])
    with ensure_patch, session_patch:
        payload = _run(system_settings_service.default_templates_list(user={"role": "B"}))
    assert [item["templateType"] for item in payload["items"]] == ["business"]
    assert payload["templateTypes"] == [{"key": "business", "label": "商务标"}]


def test_default_templates_list_tb_and_roleless_see_all() -> None:
    for user in ({"role": "TB"}, None, {"role": "member"}):
        rows = [_template(1, "technical"), _template(2, "business")]
        ensure_patch, session_patch = _patch_db([_FakeResult(rows)])
        with ensure_patch, session_patch:
            payload = _run(system_settings_service.default_templates_list(user=user))
        assert {item["templateType"] for item in payload["items"]} == {"technical", "business"}
        assert len(payload["templateTypes"]) == 2


# ===== upload / activate / delete 角色校验 =====

def test_default_template_upload_rejects_type_outside_role() -> None:
    ensure_patch, session_patch = _patch_db([])
    with ensure_patch, session_patch:
        with pytest.raises(PeripheralError) as exc_info:
            _run(
                system_settings_service.default_template_upload(
                    template_type="business",
                    file_name="商务标模板.docx",
                    version="2026.07",
                    data=b"fake-docx",
                    user={"role": "T"},
                )
            )
    assert exc_info.value.status_code == 403


def test_default_template_upload_without_role_passes_role_check() -> None:
    # 无角色信息不过滤：角色校验通过后才会走到 DOCX 内容校验（400 而非 403）
    ensure_patch, session_patch = _patch_db([])
    with ensure_patch, session_patch:
        with pytest.raises(PeripheralError) as exc_info:
            _run(
                system_settings_service.default_template_upload(
                    template_type="business",
                    file_name="商务标模板.docx",
                    version="2026.07",
                    data=b"fake-docx",
                    user=None,
                )
            )
    assert exc_info.value.status_code == 400


def test_default_template_activate_rejects_type_outside_role() -> None:
    target = _template(7, "business")
    ensure_patch, session_patch = _patch_db([_FakeResult([target])])
    with ensure_patch, session_patch:
        with pytest.raises(PeripheralError) as exc_info:
            _run(system_settings_service.default_template_activate("TPL-0007", user={"role": "T"}))
    assert exc_info.value.status_code == 403


def test_default_template_activate_allows_matching_role() -> None:
    target = _template(7, "business")
    results = [_FakeResult([target]), _FakeResult([target]), _FakeResult([target])]
    ensure_patch, session_patch = _patch_db(results)
    with ensure_patch, session_patch, patch.object(
        system_settings_module.audit_service, "record", new=AsyncMock()
    ):
        payload = _run(system_settings_service.default_template_activate("TPL-0007", user={"role": "B"}))
    assert payload["message"] == "Activated"
    assert payload["item"]["id"] == "TPL-0007"
    assert all(item["templateType"] == "business" for item in payload["items"])


def test_default_template_delete_rejects_type_outside_role() -> None:
    target = _template(8, "technical")
    ensure_patch, session_patch = _patch_db([_FakeResult([target])])
    with ensure_patch, session_patch:
        with pytest.raises(PeripheralError) as exc_info:
            _run(system_settings_service.default_template_delete("TPL-0008", user={"role": "B"}))
    assert exc_info.value.status_code == 403


# ===== opencode runtime 配置：禁用时删除文件 =====

def test_write_opencode_runtime_config_writes_then_deletes_on_disable() -> None:
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        with patch.object(system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path):
            written = system_settings_service._write_opencode_runtime_config(_llm_config())
            assert written == str(runtime_path)
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            assert runtime["model"] == "mimo/demo-model"

            removed = system_settings_service._write_opencode_runtime_config(_llm_config(enabled=False))
            assert removed == ""
            assert not runtime_path.exists()


def test_write_opencode_runtime_config_deletes_when_base_url_empty() -> None:
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        with patch.object(system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path):
            system_settings_service._write_opencode_runtime_config(_llm_config())
            assert runtime_path.exists()

            removed = system_settings_service._write_opencode_runtime_config(_llm_config(baseUrl=""))
            assert removed == ""
            assert not runtime_path.exists()


def test_write_opencode_runtime_config_delete_is_idempotent() -> None:
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        with patch.object(system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path):
            assert system_settings_service._write_opencode_runtime_config(_llm_config(enabled=False)) == ""
            assert not runtime_path.exists()


# ===== 健康检查一致性 warning =====

def _patch_llm_config(config):
    return patch.object(
        system_settings_service, "get_model_secret_config", new=AsyncMock(return_value=config)
    )


def _patch_active_config(payload):
    return patch.object(
        system_settings_service, "_fetch_opencode_active_config", new=AsyncMock(return_value=payload)
    )


def test_opencode_warning_when_active_config_differs() -> None:
    with _patch_llm_config(_llm_config()), _patch_active_config(
        {"model": "other/another-model", "provider": {}}
    ):
        warning = _run(system_settings_service._opencode_config_warning())
    assert "不一致" in warning
    assert "other/another-model" in warning


def test_opencode_no_warning_when_active_config_matches() -> None:
    with _patch_llm_config(_llm_config()), _patch_active_config(
        {
            "model": "mimo/demo-model",
            "provider": {"mimo": {"options": {"baseURL": "https://llm.example.com/v1"}}},
        }
    ):
        warning = _run(system_settings_service._opencode_config_warning())
    assert warning == ""


def test_opencode_warning_when_disabled_but_still_using_saved_config() -> None:
    with _patch_llm_config(_llm_config(enabled=False)), _patch_active_config(
        {
            "model": "mimo/demo-model",
            "provider": {"mimo": {"options": {"baseURL": "https://llm.example.com/v1"}}},
        }
    ):
        warning = _run(system_settings_service._opencode_config_warning())
    assert "已禁用" in warning


def test_opencode_warning_falls_back_to_runtime_file_mismatch() -> None:
    # /config 不可用且 runtime 文件可解析时：文件是「待重启生效」配置，不代表当前运行态，
    # 不再据文件内容判定不一致，仅提示无法获取当前生效配置
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        runtime_path.write_text(
            json.dumps({"model": "legacy/old-model", "provider": {"legacy": {"options": {"baseURL": "https://old"}}}}),
            encoding="utf-8",
        )
        with _patch_llm_config(_llm_config()), _patch_active_config(None), patch.object(
            system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path
        ):
            warning = _run(system_settings_service._opencode_config_warning())
    assert "无法获取 opencode 当前生效配置" in warning


def test_opencode_warning_fallback_disabled_with_stale_runtime_file() -> None:
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        runtime_path.write_text(json.dumps({"model": "mimo/demo-model"}), encoding="utf-8")
        with _patch_llm_config(_llm_config(enabled=False)), _patch_active_config(None), patch.object(
            system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path
        ):
            warning = _run(system_settings_service._opencode_config_warning())
        assert "已禁用" in warning

        runtime_path.unlink()
        with _patch_llm_config(_llm_config(enabled=False)), _patch_active_config(None), patch.object(
            system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path
        ):
            warning = _run(system_settings_service._opencode_config_warning())
        assert warning == ""


def test_check_opencode_attaches_warning_without_failing() -> None:
    base_item = {"id": "svc-opencode", "name": "OpenCode 服务", "status": "online", "latency": "1ms", "uptime": "-", "detail": "HTTP 200"}
    with _patch_llm_config(_llm_config()), patch.object(
        system_settings_service, "_check_http", new=AsyncMock(return_value=dict(base_item))
    ), patch.object(
        system_settings_service, "_opencode_config_warning", new=AsyncMock(return_value="配置不一致，请重启")
    ):
        item = _run(system_settings_service._check_opencode())
    assert item["status"] == "online"
    assert item["warning"] == "配置不一致，请重启"

    with _patch_llm_config(_llm_config()), patch.object(
        system_settings_service, "_check_http", new=AsyncMock(return_value=dict(base_item))
    ), patch.object(
        system_settings_service, "_opencode_config_warning", new=AsyncMock(return_value="")
    ):
        item = _run(system_settings_service._check_opencode())
    assert "warning" not in item


# ===== opencode 目标地址：健康检查与一致性比对使用 DB 的 opencodeBaseUrl =====

def test_check_opencode_uses_db_opencode_base_url() -> None:
    base_item = {"id": "svc-opencode", "name": "OpenCode 服务", "status": "online", "latency": "1ms", "uptime": "-", "detail": "HTTP 200"}
    check_http = AsyncMock(return_value=dict(base_item))
    with _patch_llm_config(_llm_config(opencodeBaseUrl="http://db-opencode:4096")), patch.object(
        system_settings_service, "_check_http", new=check_http
    ), patch.object(
        system_settings_service, "_opencode_config_warning", new=AsyncMock(return_value="")
    ):
        _run(system_settings_service._check_opencode())
    assert check_http.call_args.args[2] == "http://db-opencode:4096"


def test_opencode_config_warning_fetches_active_config_from_db_base_url() -> None:
    fetch_active = AsyncMock(return_value=None)
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        with _patch_llm_config(_llm_config(opencodeBaseUrl="http://db-opencode:4096/")), patch.object(
            system_settings_service, "_fetch_opencode_active_config", new=fetch_active
        ), patch.object(system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path):
            warning = _run(system_settings_service._opencode_config_warning())
    fetch_active.assert_awaited_once_with("http://db-opencode:4096/")
    assert "runtime 配置文件缺失" in warning


# ===== runtime 配置清除失败：抛出可感知错误 =====

def test_write_opencode_runtime_config_delete_failure_raises() -> None:
    with TemporaryDirectory() as tmp:
        runtime_path = Path(tmp) / "opencode.runtime.json"
        runtime_path.write_text("{}", encoding="utf-8")
        with patch.object(system_settings_module, "OPENCODE_RUNTIME_CONFIG_PATH", runtime_path), patch.object(
            Path, "unlink", side_effect=OSError("permission denied")
        ):
            with pytest.raises(PeripheralError) as exc_info:
                system_settings_service._write_opencode_runtime_config(_llm_config(enabled=False))
    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "OPENCODE_RUNTIME_CONFIG_CLEAR_FAILED"


# ===== _normalize_model_config：显式空串不回填 env 默认 =====

def test_normalize_model_config_keeps_explicit_empty_values() -> None:
    config = system_settings_service._normalize_model_config(
        "llm",
        _llm_config(baseUrl="", opencodeBaseUrl=""),
    )
    assert config["baseUrl"] == ""
    assert config["opencodeBaseUrl"] == ""


def test_normalize_model_config_falls_back_to_env_only_when_key_absent() -> None:
    raw = _llm_config()
    del raw["baseUrl"]
    config = system_settings_service._normalize_model_config("llm", raw)
    assert config["baseUrl"] == (settings_module.default_llm_base_url or "")
    assert config["opencodeBaseUrl"] == settings_module.opencode_base_url


# ===== update_model_config：按键存在性合并，允许显式清空 =====

def _system_config_row(value: dict) -> SystemConfig:
    return SystemConfig(key="llm", value=value, sensitive=True, updated_by="测试用户")


def _patch_update_deps(current: dict, row: SystemConfig):
    return (
        patch.object(system_settings_service, "_ensure_tables", new=AsyncMock()),
        patch.object(system_settings_service, "get_model_secret_config", new=AsyncMock(return_value=dict(current))),
        patch.object(system_settings_service, "_write_opencode_runtime_config", return_value=""),
        patch.object(system_settings_module.audit_service, "record", new=AsyncMock()),
        patch.object(
            system_settings_module,
            "async_session",
            side_effect=lambda: _FakeSession([_FakeResult([row]), _FakeResult([row])]),
        ),
    )


def test_update_model_config_allows_clearing_values_with_empty_strings() -> None:
    current = system_settings_service._normalize_model_config("llm", _llm_config(opencodeBaseUrl="http://db-opencode:4096"))
    row = _system_config_row(dict(current))
    patches = _patch_update_deps(current, row)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        _run(
            system_settings_service.update_model_config(
                "llm",
                {"enabled": True, "baseUrl": "", "opencodeBaseUrl": "", "apiKey": ""},
            )
        )
    saved = row.value
    assert saved["baseUrl"] == ""
    assert saved["opencodeBaseUrl"] == ""
    assert saved["apiKey"] == ""
    # 未传的字段保留当前值
    assert saved["providerId"] == current["providerId"]
    assert saved["modelId"] == current["modelId"]


def test_update_model_config_keeps_current_values_when_keys_absent() -> None:
    current = system_settings_service._normalize_model_config("llm", _llm_config(opencodeBaseUrl="http://db-opencode:4096"))
    row = _system_config_row(dict(current))
    patches = _patch_update_deps(current, row)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        _run(system_settings_service.update_model_config("llm", {"enabled": False}))
    saved = row.value
    assert saved["enabled"] is False
    assert saved["baseUrl"] == current["baseUrl"]
    assert saved["opencodeBaseUrl"] == current["opencodeBaseUrl"]
    assert saved["apiKey"] == current["apiKey"]
