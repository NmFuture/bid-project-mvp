from __future__ import annotations

import asyncio
from unittest.mock import patch
from app.core.config import settings
from app.services.agent_engine.base import EngineRunResult
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.system_settings import system_settings_service

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
    _db_llm_config,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_init_uses_db_config_when_llm_active(self) -> None:
        with patch.object(
            system_settings_service,
            "get_opencode_model_config_sync",
            return_value=_db_llm_config(),
        ):
            client = OpencodeEngine()
        self.assertEqual(client.base_url, "http://db-opencode:4096")
        self.assertEqual(client.provider_id, "custom-provider")
        self.assertEqual(client.model_id, "custom-model")



    async def test_init_falls_back_to_env_config_when_llm_not_active(self) -> None:
        for config in (
            _db_llm_config(enabled=False),
            _db_llm_config(baseUrl=""),
        ):
            with self.subTest(config=config), patch.object(
                system_settings_service,
                "get_opencode_model_config_sync",
                return_value=config,
            ):
                client = OpencodeEngine()
            self.assertEqual(client.base_url, settings.opencode_base_url.rstrip("/"))
            self.assertEqual(client.provider_id, settings.opencode_provider_id)
            self.assertEqual(client.model_id, settings.opencode_model_id)



    async def test_repair_examples_keep_technical_reports_empty_and_business_reports_unchanged(self) -> None:
        client = OpencodeEngine()
        prompts: list[str] = []

        def fake_run_session(_session_id: str, prompt: str, **_kwargs: object) -> EngineRunResult:
            prompts.append(prompt)
            return EngineRunResult(session_id=_session_id, reply_text="{}")

        with (
            patch.object(client, "create_session", return_value="repair"),
            patch.object(client, "run_session", side_effect=fake_run_session),
        ):
            await client._repair_json_payload("broken", "assembly")
            await client._repair_json_payload("broken", "business_format")

        technical_prompt, business_prompt = prompts
        self.assertIn('"assemblyReport":""', technical_prompt)
        self.assertIn('"needsReview":""', technical_prompt)
        self.assertIn('"summary":', technical_prompt)
        self.assertIn('"warnings":[', technical_prompt)
        self.assertNotIn("assembly_report.md", technical_prompt)
        self.assertNotIn("needs_review.md", technical_prompt)
        self.assertIn("business_format_clean_report.md", business_prompt)



    async def test_constructor_uses_supplied_model_config_without_loading_system_settings(self) -> None:
        model_config = _db_llm_config(
            opencodeBaseUrl="http://configured-opencode:4096",
            providerId="configured-provider",
            modelId="configured-model",
            timeoutMs=45000,
        )

        with patch(
            "app.services.agent_engine.opencode_engine.system_settings_service.get_opencode_model_config_sync"
        ) as load_config:
            client = OpencodeEngine(model_config=model_config)

        load_config.assert_not_called()
        self.assertEqual(client.base_url, "http://configured-opencode:4096")
        self.assertEqual(client.provider_id, "configured-provider")
        self.assertEqual(client.model_id, "configured-model")
        self.assertEqual(client.timeout.read, 45.0)



    async def test_constructor_falls_back_when_supplied_model_config_is_inactive(self) -> None:
        model_config = _db_llm_config(enabled=False)

        with patch(
            "app.services.agent_engine.opencode_engine.system_settings_service.get_opencode_model_config_sync"
        ) as load_config:
            client = OpencodeEngine(model_config=model_config)

        load_config.assert_not_called()
        self.assertEqual(client.base_url, settings.opencode_base_url.rstrip("/"))
        self.assertEqual(client.provider_id, settings.opencode_provider_id)
        self.assertEqual(client.model_id, settings.opencode_model_id)



    async def test_sync_model_config_load_waits_for_database_by_default(self) -> None:
        async def slow_config_load(_kind: str) -> dict:
            await asyncio.sleep(0.02)
            return _db_llm_config(modelId="database-model")

        with patch.object(
            system_settings_service,
            "get_model_secret_config",
            new=slow_config_load,
        ):
            config = system_settings_service.get_opencode_model_config_sync()

        self.assertEqual(config["modelId"], "database-model")
