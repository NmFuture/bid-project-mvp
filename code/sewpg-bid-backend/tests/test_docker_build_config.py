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


def test_docling_worker_dependencies_lock_cpu_and_cuda_torch_separately() -> None:
    worker_requirements = _requirement_lines(BACKEND_ROOT / "requirements-docling-worker.txt")
    cpu_torch_requirements = _requirement_lines(BACKEND_ROOT / "requirements-torch-cpu.txt")
    cuda_torch_requirements = _requirement_lines(BACKEND_ROOT / "requirements-torch-cuda.txt")
    docling_lock = _requirement_lines(BACKEND_ROOT / "requirements-docling-lock.txt")

    assert "-c requirements-docling-lock.txt" in worker_requirements
    assert "docling==2.108.0" in worker_requirements
    assert "onnxruntime==1.27.0" in worker_requirements
    assert "torch==2.12.1+cpu" in cpu_torch_requirements
    assert "torchvision==0.27.1+cpu" in cpu_torch_requirements
    assert "torch==2.12.1+cu130" in cuda_torch_requirements
    assert "torchvision==0.27.1+cu130" in cuda_torch_requirements
    assert "docling-slim==2.108.0" in docling_lock
    assert not any(line.startswith(("torch==", "torchvision==")) for line in docling_lock)
    assert not any(line.startswith(("cuda-", "nvidia-", "triton==")) for line in docling_lock)


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
    pillow_install = 'pip install --index-url "${PIP_INDEX_URL}" -c requirements-docling-lock.txt pillow'
    torch_install = 'pip install --index-url "${PYTORCH_CPU_INDEX_URL}" -r requirements-torch-cpu.txt'

    assert "ARG PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu" in dockerfile
    assert pillow_install in dockerfile
    assert torch_install in dockerfile
    assert dockerfile.index(pillow_install) < dockerfile.index(torch_install)
    assert "pip install --extra-index-url" in dockerfile
    assert "pip check" in dockerfile
    assert "torch.version.cuda is None" in dockerfile
    assert "BID_DOCLING_ARTIFACTS_PATH=/opt/docling-models" in dockerfile
    assert "python scripts/download_docling_models.py /opt/docling-models" in dockerfile
    assert 'CMD ["python", "-m", "app.workers.docling_worker"]' in dockerfile


def test_docling_cuda_worker_uses_pytorch_cu130_and_models() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile.docling-worker.cuda").read_text(encoding="utf-8")

    assert "ARG PYTORCH_CUDA_INDEX_URL=https://download.pytorch.org/whl/cu130" in dockerfile
    assert 'pip install --index-url "${PYTORCH_CUDA_INDEX_URL}" -r requirements-torch-cuda.txt' in dockerfile
    assert "torch.version.cuda == '13.0'" in dockerfile
    assert "DOCLING_DEVICE=cuda" in dockerfile
    assert "python scripts/download_docling_models.py /opt/docling-models" in dockerfile


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


def test_compose_uses_separate_material_worker() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    material_worker = services["material-worker"]

    assert material_worker["image"] == services["fastapi"]["image"]
    assert material_worker["command"] == ["python", "-m", "app.workers.material_worker"]
    assert material_worker["container_name"] == "sewpg_bid_material_worker"
    assert material_worker["environment"]["REDIS_MATERIAL_QUEUE_KEY"] == (
        "${REDIS_MATERIAL_QUEUE_KEY:-bid:jobs:material}"
    )
    assert material_worker["volumes"] == services["worker"]["volumes"]

    second = yaml.safe_load((CODE_ROOT / "docker-compose.second.yml").read_text(encoding="utf-8"))
    airgap = yaml.safe_load((CODE_ROOT / "docker-compose.airgap.yml").read_text(encoding="utf-8"))
    assert second["services"]["material-worker"]["container_name"] == "sewpg_bid_second_material_worker"
    assert airgap["services"]["material-worker"]["pull_policy"] == "never"


def test_compose_overrides_include_docling_worker_and_bind_ocr_to_gpu_zero() -> None:
    second = yaml.safe_load((CODE_ROOT / "docker-compose.second.yml").read_text(encoding="utf-8"))
    airgap = yaml.safe_load((CODE_ROOT / "docker-compose.airgap.yml").read_text(encoding="utf-8"))
    ocr = yaml.safe_load((CODE_ROOT / "docker-compose.ocr.yml").read_text(encoding="utf-8"))["services"]["ocr"]

    assert second["services"]["docling-worker"]["container_name"] == "sewpg_bid_second_docling_worker"
    assert airgap["services"]["docling-worker"]["pull_policy"] == "never"
    assert "DOCLING_IMAGE" in airgap["services"]["docling-worker"]["image"]
    assert airgap["services"]["postgres"]["pull_policy"] == "never"
    assert airgap["services"]["minio"]["pull_policy"] == "never"
    assert "gpus" not in ocr
    devices = ocr["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [
        {
            "driver": "nvidia",
            "device_ids": ["${OCR_GPU_DEVICE_ID:-0}"],
            "capabilities": ["gpu"],
        }
    ]
    assert ocr["environment"]["NVIDIA_VISIBLE_DEVICES"] == "${OCR_GPU_DEVICE_ID:-0}"
    assert ocr["environment"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert ocr["environment"]["HF_ENDPOINT"] == "${HF_ENDPOINT:-https://huggingface.co}"


def test_5090_overlay_binds_docling_and_ocr_only_to_gpu_zero() -> None:
    overlay = yaml.safe_load((CODE_ROOT / "docker-compose.5090.yml").read_text(encoding="utf-8"))

    assert set(overlay["services"]) == {"docling-worker", "ocr"}
    for service_name in ("docling-worker", "ocr"):
        service = overlay["services"][service_name]
        assert service["environment"]["NVIDIA_VISIBLE_DEVICES"] == "0"
        assert service["environment"]["CUDA_VISIBLE_DEVICES"] == "0"

    docling_worker = overlay["services"]["docling-worker"]
    devices = docling_worker["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [{"driver": "nvidia", "device_ids": ["0"], "capabilities": ["gpu"]}]
    assert docling_worker["build"]["dockerfile"] == "Dockerfile.docling-worker.cuda"
    assert docling_worker["environment"]["DOCLING_DEVICE"] == "cuda"
    assert "cu130" in docling_worker["build"]["args"]["PYTORCH_CUDA_INDEX_URL"]

    rendered = (CODE_ROOT / "docker-compose.5090.yml").read_text(encoding="utf-8")
    assert "gpus: all" not in rendered
    assert 'device_ids: ["1"]' not in rendered


def test_airgap_build_scripts_export_docling_image() -> None:
    shell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.sh").read_text(encoding="utf-8")
    powershell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.ps1").read_text(encoding="utf-8")

    for script in (shell_script, powershell_script):
        assert "sewpg-bid/docling-worker:" in script
        assert "docling-worker" in script
        assert "DOCLING_IMAGE" in script.upper()
        assert "pgvector/pgvector:pg16" in script
        assert "minio/minio:RELEASE.2025-04-22T22-12-26Z" in script
        assert "initdb" in script
        assert "onlyoffice" in script
        assert "MAIN_SHA" in script
        assert "SHA256SUMS" in script


def test_5090_release_scripts_build_off_host_and_never_build_on_target() -> None:
    bundle_script = (CODE_ROOT / "scripts" / "build-5090-bundle.sh").read_text(encoding="utf-8")
    target_script = (CODE_ROOT / "scripts" / "up-5090.sh").read_text(encoding="utf-8")
    generic_bundle_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.sh").read_text(encoding="utf-8")

    assert "DEPLOY_TARGET=5090" in bundle_script
    assert "INCLUDE_OCR=true" in bundle_script
    assert 'DEPLOY_TARGET="${DEPLOY_TARGET:-generic}"' in generic_bundle_script
    assert 'docker-compose.5090.yml' in generic_bundle_script
    assert '"ocrSourceDigest"' in generic_bundle_script
    assert '"gitSha"' in generic_bundle_script
    assert 'POSTGRES_SOURCE_IMAGE="${POSTGRES_SOURCE_IMAGE:-pgvector/pgvector:pg16}"' in generic_bundle_script
    assert 'MINIO_SOURCE_IMAGE="${MINIO_SOURCE_IMAGE:-minio/minio:RELEASE.2025-04-22T22-12-26Z}"' in generic_bundle_script

    assert "docker pull" not in target_script
    assert "docker compose build" not in target_script
    assert "up -d --no-build" in target_script
    assert 'require_changed OPENCODE_MODEL_ID replace-with-your-internal-model' in target_script
    assert 'require_changed DEFAULT_LLM_MODEL replace-with-your-internal-model' in target_script
    assert 'require_changed DATABASE_URL postgresql+asyncpg://biduser:bidpass@postgres:5432/bidplatform' in target_script
    assert 'require_changed POSTGRES_PASSWORD bidpass' in target_script
    assert 'require_changed MINIO_ROOT_PASSWORD minioadmin' in target_script
    assert 'require_changed AUTH_ADMIN_PASSWORD 123456' in target_script
    assert 'devices[0].get("device_ids") != ["0"]' in target_script


def test_airgap_env_template_contains_required_5090_settings() -> None:
    env_template = (CODE_ROOT / ".env.airgap.example").read_text(encoding="utf-8")

    for setting in (
        "AUTH_ADMIN_EMAIL=admin@sewpg.com",
        "AUTH_ADMIN_PASSWORD=123456",
        "AUTH_ADMIN_NAME=管理员",
        "OCR_GPU_DEVICE_ID=0",
        "DEFAULT_LLM_MODEL=replace-with-your-internal-model",
    ):
        assert setting in env_template
