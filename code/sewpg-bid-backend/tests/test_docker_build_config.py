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


def test_fastapi_requirements_do_not_include_docling_runtime() -> None:
    requirements = _requirement_lines(BACKEND_ROOT / "requirements.txt")

    assert "-c requirements-docling-lock.txt" not in requirements
    assert not any(line.startswith("docling") for line in requirements)
    assert not any(line.startswith("torch") for line in requirements)
    assert not any(line.startswith("onnxruntime") for line in requirements)


def test_docling_worker_dependencies_are_cpu_only_and_locked() -> None:
    worker_requirements = _requirement_lines(BACKEND_ROOT / "requirements-docling-worker.txt")
    torch_requirements = _requirement_lines(BACKEND_ROOT / "requirements-torch-cpu.txt")
    docling_lock = _requirement_lines(BACKEND_ROOT / "requirements-docling-lock.txt")

    assert "-c requirements-docling-lock.txt" in worker_requirements
    assert "docling==2.108.0" in worker_requirements
    assert "onnxruntime==1.27.0" in worker_requirements
    assert "torch==2.12.1+cpu" in torch_requirements
    assert "torchvision==0.27.1+cpu" in torch_requirements
    assert "docling-slim==2.108.0" in docling_lock
    assert "torch==2.12.1+cpu" in docling_lock
    assert "torchvision==0.27.1+cpu" in docling_lock
    assert not any(line.startswith(("cuda-", "nvidia-", "triton==")) for line in docling_lock)


def test_fastapi_dockerfile_is_lightweight_and_keeps_pip_cache() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY requirements.txt ./" in dockerfile
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "pip install -r requirements.txt" in dockerfile
    assert "download_docling_models.py" not in dockerfile
    assert "BID_DOCLING_ARTIFACTS_PATH" not in dockerfile
    assert "HF_ENDPOINT" not in dockerfile


def test_docling_worker_dockerfile_installs_cpu_torch_and_models() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile.docling-worker").read_text(encoding="utf-8")

    assert "ARG PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu" in dockerfile
    assert 'pip install --index-url "${PYTORCH_CPU_INDEX_URL}" -r requirements-torch-cpu.txt' in dockerfile
    assert "pip install --extra-index-url" in dockerfile
    assert "pip check" in dockerfile
    assert "torch.version.cuda is None" in dockerfile
    assert "BID_DOCLING_ARTIFACTS_PATH=/opt/docling-models" in dockerfile
    assert "python scripts/download_docling_models.py /opt/docling-models" in dockerfile
    assert 'CMD ["python", "-m", "app.workers.docling_worker"]' in dockerfile


def test_compose_uses_separate_docling_worker_and_shared_volumes() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    docling_worker = services["docling-worker"]

    assert services["worker"]["image"] == services["fastapi"]["image"]
    assert "build" not in services["worker"]
    assert docling_worker["image"] != services["fastapi"]["image"]
    assert docling_worker["build"]["dockerfile"] == "Dockerfile.docling-worker"
    assert docling_worker["command"] == ["python", "-m", "app.workers.docling_worker"]
    assert "uploads:/data/uploads:ro" in docling_worker["volumes"]
    assert "documents:/data/documents:ro" in docling_worker["volumes"]
    assert "parsed:/data/parsed" in docling_worker["volumes"]
    assert "gpus" not in docling_worker
    assert "deploy" not in docling_worker
    assert docling_worker["cpus"] == "${DOCLING_CPU_LIMIT:-8.0}"
    assert docling_worker["mem_limit"] == "${DOCLING_MEMORY_LIMIT:-32g}"
    assert docling_worker["environment"]["DOCUMENTS_DIR"] == "/data/documents"
    assert docling_worker["environment"]["OMP_NUM_THREADS"] == "${DOCLING_CPU_THREADS:-8}"
    assert docling_worker["environment"]["BID_DOCLING_ARTIFACTS_PATH"] == "/opt/docling-models"
    assert "docling-worker-ready" in " ".join(docling_worker["healthcheck"]["test"])
    assert "docling_models" not in compose["volumes"]

    for service_name in ("fastapi", "worker"):
        assert "BID_DOCLING_ARTIFACTS_PATH" not in services[service_name]["environment"]
        assert all("docling-models" not in volume for volume in services[service_name]["volumes"])


def test_compose_overrides_include_docling_worker_and_bind_ocr_to_gpu_one() -> None:
    second = yaml.safe_load((CODE_ROOT / "docker-compose.second.yml").read_text(encoding="utf-8"))
    airgap = yaml.safe_load((CODE_ROOT / "docker-compose.airgap.yml").read_text(encoding="utf-8"))
    ocr = yaml.safe_load((CODE_ROOT / "docker-compose.ocr.yml").read_text(encoding="utf-8"))["services"]["ocr"]

    assert second["services"]["docling-worker"]["container_name"] == "sewpg_bid_second_docling_worker"
    assert airgap["services"]["docling-worker"]["pull_policy"] == "never"
    assert "DOCLING_IMAGE" in airgap["services"]["docling-worker"]["image"]
    assert "gpus" not in ocr
    devices = ocr["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [
        {
            "driver": "nvidia",
            "device_ids": ["${OCR_GPU_DEVICE_ID:-1}"],
            "capabilities": ["gpu"],
        }
    ]


def test_airgap_build_scripts_export_docling_image() -> None:
    shell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.sh").read_text(encoding="utf-8")
    powershell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.ps1").read_text(encoding="utf-8")

    for script in (shell_script, powershell_script):
        assert "sewpg-bid/docling-worker:" in script
        assert "docling-worker" in script
        assert "DOCLING_IMAGE" in script.upper()
