from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.services.wiki_export import export_wiki, wiki_api_path


def test_wiki_api_path_is_workspace_scoped() -> None:
    assert wiki_api_path("技术标") == "/api/technical/materials/wiki"
    assert wiki_api_path("商务标") == "/api/business/materials/wiki"


def test_wiki_api_path_requires_known_bid_type() -> None:
    with pytest.raises(ValueError):
        wiki_api_path("")
    with pytest.raises(ValueError):
        wiki_api_path("unknown")


def test_export_wiki_uses_technical_workspace_api() -> None:
    with TemporaryDirectory() as temp_dir:
        with patch("app.services.wiki_export.fetch_json", return_value={"tree": []}) as fetch:
            export_wiki("http://fastapi:8000", "技术标", Path(temp_dir))

    requested_url = fetch.call_args.args[0]
    assert "/api/technical/materials/wiki?" in requested_url
    assert "/api/materials/wiki?" not in requested_url


def test_export_wiki_uses_business_workspace_api() -> None:
    with TemporaryDirectory() as temp_dir:
        with patch("app.services.wiki_export.fetch_json", return_value={"tree": []}) as fetch:
            export_wiki("http://fastapi:8000", "商务标", Path(temp_dir))

    requested_url = fetch.call_args.args[0]
    assert "/api/business/materials/wiki?" in requested_url
    assert "/api/materials/wiki?" not in requested_url
