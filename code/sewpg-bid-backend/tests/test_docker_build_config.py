from pathlib import Path

import yaml


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = BACKEND_ROOT.parent


def _requirement_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def test_docling_runtime_dependencies_are_locked() -> None:
    requirements = _requirement_lines(BACKEND_ROOT / "requirements.txt")
    docling_lock = _requirement_lines(BACKEND_ROOT / "requirements-docling-lock.txt")

    assert "-c requirements-docling-lock.txt" in requirements
    assert "docling==2.108.0" in requirements
    assert "onnxruntime==1.27.0" in requirements

    assert "docling-slim==2.108.0" in docling_lock
    assert "torch==2.12.1" in docling_lock
    assert "torchvision==0.27.1" in docling_lock
    assert "nvidia-cublas==13.1.1.3" in docling_lock


def test_docxcompose_floor_supports_preserve_styles() -> None:
    expected = "docxcompose>=2.2.0"
    requirements = _requirement_lines(BACKEND_ROOT / "requirements.txt")
    opencode_dockerfile = (BACKEND_ROOT / "opencode" / "Dockerfile").read_text(encoding="utf-8")

    requirement_specs = {line for line in requirements if line.startswith("docxcompose")}
    dockerfile_specs = {
        token.strip('"')
        for token in opencode_dockerfile.split()
        if token.strip('"').startswith("docxcompose")
    }

    assert requirement_specs == {expected}
    assert dockerfile_specs == {expected}


def test_backend_dockerfile_keeps_pip_download_cache() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY requirements*.txt ./" in dockerfile
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "pip install -r requirements.txt" in dockerfile
    assert "--no-cache-dir -r requirements.txt" not in dockerfile


def test_backend_dockerfile_preloads_docling_models() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "BID_DOCLING_ARTIFACTS_PATH=/opt/docling-models" in dockerfile
    assert "ARG HF_ENDPOINT=https://hf-mirror.com" in dockerfile
    assert "HF_ENDPOINT=${HF_ENDPOINT}" in dockerfile
    assert "HF_HUB_DISABLE_XET=1" in dockerfile
    assert "scripts/download_docling_models.py" in dockerfile
    assert "python scripts/download_docling_models.py /opt/docling-models" in dockerfile
    assert "\n    DOCLING_ARTIFACTS_PATH=" not in dockerfile
    assert "\nENV DOCLING_ARTIFACTS_PATH=" not in dockerfile


def test_worker_reuses_fastapi_image_without_duplicate_build() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "build" in services["fastapi"]
    assert services["fastapi"]["build"]["args"]["HF_ENDPOINT"] == "${HF_ENDPOINT:-https://hf-mirror.com}"
    assert services["worker"]["image"] == services["fastapi"]["image"]
    assert "build" not in services["worker"]


def test_compose_does_not_force_empty_docling_artifacts_path() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("fastapi", "worker"):
        environment = services[service_name]["environment"]
        assert "DOCLING_ARTIFACTS_PATH" not in environment
        assert environment["BID_DOCLING_ARTIFACTS_PATH"].endswith(":-/opt/docling-models}}")
