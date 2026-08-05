import json
import os
import subprocess
from pathlib import Path
import tempfile

import yaml


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = BACKEND_ROOT.parent


def _requirement_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _run_onlyoffice_image_policy(
    image: str,
    expected_image: str = "sewpg-bid/onlyoffice:replacement-fontpack-v1",
    other_service_image: str = "redis:7-alpine",
) -> subprocess.CompletedProcess[str]:
    policy_path = BACKEND_ROOT / "onlyoffice" / "image-policy.sh"
    environment = {
        **os.environ,
        "TEST_EXPECTED_ONLYOFFICE_IMAGE": expected_image,
        "TEST_ONLYOFFICE_IMAGE": image,
        "TEST_OTHER_SERVICE_IMAGE": other_service_image,
        "TEST_ONLYOFFICE_POLICY": str(policy_path),
    }
    script = r'''
set -euo pipefail
docker() {
  case "$*" in
    *"config --format json"*)
      printf '{"services":{"onlyoffice":{"image":"%s"},"redis":{"image":"%s"}}}\n' \
        "${TEST_ONLYOFFICE_IMAGE}" "${TEST_OTHER_SERVICE_IMAGE}"
      ;;
    *) return 2 ;;
  esac
}
source "${TEST_ONLYOFFICE_POLICY}"
require_expected_onlyoffice_image \
  /tmp/test.env "${TEST_EXPECTED_ONLYOFFICE_IMAGE}" \
  "ONLYOFFICE_IMAGE=${TEST_EXPECTED_ONLYOFFICE_IMAGE}" \
  -f /tmp/docker-compose.yml
'''
    return subprocess.run(
        ["bash", "-c", script],
        cwd=CODE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_docling_worker_timing_import_stays_postgres_free() -> None:
    worker_source = (BACKEND_ROOT / "app" / "workers" / "docling_worker.py").read_text(encoding="utf-8")
    events_source = (BACKEND_ROOT / "app" / "services" / "job_timing_events.py").read_text(encoding="utf-8")

    assert "from app.services.job_timing_events import track_job_timing" in worker_source
    assert "app.services.job_timing import" not in worker_source
    assert "psycopg" not in events_source
    assert "DATABASE_URL" not in events_source


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
    assert "DATABASE_URL" not in docling_worker["environment"]
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


def test_onlyoffice_image_contains_and_verifies_the_open_source_font_contract() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    onlyoffice = compose["services"]["onlyoffice"]
    font_root = BACKEND_ROOT / "onlyoffice"
    dockerfile = (font_root / "Dockerfile").read_text(encoding="utf-8")
    extractor = (font_root / "extract-noto-sc.py").read_text(encoding="utf-8")
    contract = json.loads((font_root / "font-contract.json").read_text(encoding="utf-8"))

    assert onlyoffice["image"] == "${ONLYOFFICE_IMAGE:-sewpg-bid/onlyoffice:dev-fontpack-v1}"
    assert onlyoffice["build"]["context"] == "./sewpg-bid-backend/onlyoffice"
    assert onlyoffice["build"]["args"] == {
        "ONLYOFFICE_BASE_IMAGE": (
            "${ONLYOFFICE_BASE_IMAGE:-onlyoffice/documentserver:9.3.1.2@sha256:"
            "0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31}"
        ),
        "ONLYOFFICE_FONT_BUILDER_IMAGE": (
            "${ONLYOFFICE_FONT_BUILDER_IMAGE:-debian:bookworm-slim@sha256:"
            "63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e}"
        ),
        "SEWPG_BUILD_REVISION": "${ONLYOFFICE_BUILD_REVISION:-dev}",
    }
    assert all("/usr/share/fonts" not in volume for volume in onlyoffice["volumes"])
    assert "sewpg-verify-fonts" in " ".join(onlyoffice["healthcheck"]["test"])
    assert "ARG FONTTOOLS_PACKAGE_VERSION=4.38.0-1+deb12u1" in dockerfile
    assert 'python3-fonttools="${FONTTOOLS_PACKAGE_VERSION}"' in dockerfile
    assert 'org.opencontainers.image.revision="${SEWPG_BUILD_REVISION}"' in dockerfile
    assert "TTCollection(args.source, recalcTimestamp=False)" in extractor
    assert "fonts-noto-cjk" in dockerfile
    assert "fonts-liberation2" in dockerfile
    assert "extract-noto-sc.py" in dockerfile
    assert "/usr/share/doc/fonts-noto-cjk/copyright" in dockerfile
    assert "/usr/share/doc/fonts-liberation2/copyright" in dockerfile
    assert {font["family"] for font in contract["fonts"]} == {
        "Noto Sans CJK SC",
        "Noto Serif CJK SC",
        "Liberation Serif",
        "Liberation Sans",
    }
    assert not (font_root / "fonts" / "Songti.ttc").exists()
    assert not (font_root / "fonts" / "ArialUnicode.ttf").exists()


def test_onlyoffice_image_policy_rejects_legacy_images_and_accepts_release_tags() -> None:
    legacy_images = (
        "onlyoffice/documentserver:9.3.1.2",
        "docker.io/onlyoffice/documentserver@sha256:" + "a" * 64,
        "sewpg-bid/onlyoffice:9.3.1.2",
        "sewpg-bid/onlyoffice:9.3.1.2-fontpack-v1",
        "sewpg-bid/onlyoffice:9.3.1.2-fontpack-v1@sha256:" + "a" * 64,
        "registry.example.com/team/onlyoffice:9.3.1.2",
    )
    for image in legacy_images:
        completed = _run_onlyoffice_image_policy(image)
        assert completed.returncode == 1, completed.stderr
        assert "Unexpected OnlyOffice image configuration." in completed.stderr
        assert "Expected: sewpg-bid/onlyoffice:replacement-fontpack-v1" in completed.stderr

    release_images = (
        "sewpg-bid/onlyoffice:dev-fontpack-v1",
        "sewpg-bid/onlyoffice:main-0123456789ab-fontpack-v1",
        "sewpg-bid/onlyoffice:offline-202608041200-fontpack-v1",
    )
    for image in release_images:
        completed = _run_onlyoffice_image_policy(image, expected_image=image)
        assert completed.returncode == 0, completed.stderr
        assert completed.stderr == ""

    expected = "sewpg-bid/onlyoffice:dev-fontpack-v1"
    mixed_services = _run_onlyoffice_image_policy(
        "onlyoffice/documentserver:9.3.1.2",
        expected_image=expected,
        other_service_image=expected,
    )
    assert mixed_services.returncode == 1
    assert "Actual:   onlyoffice/documentserver:9.3.1.2" in mixed_services.stderr


def test_onlyoffice_airgap_template_parser_accepts_windows_crlf() -> None:
    policy_path = BACKEND_ROOT / "onlyoffice" / "image-policy.sh"
    expected = b"sewpg-bid/onlyoffice:offline-test-fontpack-v1"
    with tempfile.TemporaryDirectory() as directory:
        env_path = Path(directory) / ".env.airgap.example"
        env_path.write_bytes(b"ONLYOFFICE_IMAGE=" + expected + b"\r\n")
        completed = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; onlyoffice_image_from_env_template "$2" | tr -d "\\n"',
                "test-policy",
                str(policy_path),
                str(env_path),
            ],
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == expected


def test_onlyoffice_start_scripts_validate_images_and_build_on_online_paths() -> None:
    start_local = (CODE_ROOT / "start-local.sh").read_text(encoding="utf-8")
    up_ocr = (CODE_ROOT / "scripts" / "up-ocr.sh").read_text(encoding="utf-8")
    up_airgap = (CODE_ROOT / "scripts" / "up-airgap.sh").read_text(encoding="utf-8")
    up_5090 = (CODE_ROOT / "scripts" / "up-5090.sh").read_text(encoding="utf-8")

    for script in (start_local, up_ocr, up_airgap, up_5090):
        assert "onlyoffice/image-policy.sh" in script
        assert "require_expected_onlyoffice_image" in script

    local_build = 'docker compose "${COMPOSE_ARGS[@]}" build --provenance=false onlyoffice'
    local_up = 'docker compose "${COMPOSE_ARGS[@]}" up -d --no-build'
    assert start_local.index("require_expected_onlyoffice_image") < start_local.index(local_build)
    assert start_local.index(local_build) < start_local.index(local_up)

    ocr_build = 'docker compose "${COMPOSE_ARGS[@]}" build --provenance=false'
    ocr_up = 'docker compose "${COMPOSE_ARGS[@]}" up -d --no-build'
    assert up_ocr.index("require_expected_onlyoffice_image") < up_ocr.index(ocr_build)
    assert up_ocr.index(ocr_build) < up_ocr.index(ocr_up)
    assert "fastapi docling-worker opencode web onlyoffice" in up_ocr

    airgap_up = 'docker compose "${compose_args[@]}" up -d --no-build'
    assert up_airgap.index("require_expected_onlyoffice_image") < up_airgap.index(airgap_up)
    assert 'docker compose "${compose_args[@]}" build' not in up_airgap
    assert "copy ONLYOFFICE_IMAGE from ${ROOT_DIR}/.env.airgap.example" in up_airgap

    assert 'ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:${RELEASE_TAG}-fontpack-v1"' in up_5090
    assert up_5090.index("require_expected_onlyoffice_image") < up_5090.index("config --quiet")
    assert "web fastapi docling-worker opencode onlyoffice" in up_5090
    assert "copy ONLYOFFICE_IMAGE from ${ROOT_DIR}/.env.airgap.example" in up_5090


def test_compose_uses_one_opencode_service_for_parallel_chapter_sessions() -> None:
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert sorted(name for name in services if name.startswith("opencode")) == ["opencode"]
    for service_name in ("fastapi", "worker"):
        assert services[service_name]["environment"]["OPENCODE_CHAPTER_BASE_URLS"] == (
            "${OPENCODE_CHAPTER_BASE_URLS:-http://opencode:4096}"
        )
        assert services[service_name]["environment"]["TECH_OUTLINE_LLM_FINALIZE"] == (
            "${TECH_OUTLINE_LLM_FINALIZE:-false}"
        )
    assert sorted(
        name for name in compose["volumes"] if name.startswith("opencode_")
    ) == ["opencode_cache", "opencode_data"]

    env_example = (CODE_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "TECH_OUTLINE_LLM_FINALIZE=false" in env_example


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
    loader_script = (CODE_ROOT / "scripts" / "load-airgap-images.sh").read_text(encoding="utf-8")

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
        assert "onlyofficeImageId" in script
        assert "ONLYOFFICE_BUILD_REVISION" in script
        assert "ONLYOFFICE_FONT_BUILDER_IMAGE" in script
        assert "--provenance=false" in script

    assert 'ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:${TAG}-fontpack-v1"' in shell_script
    assert "CHECKSUM_COMMAND=(sha256sum -c)" in loader_script
    assert "CHECKSUM_COMMAND=(shasum -a 256 -c)" in loader_script
    assert 'docker image inspect --format \'{{.Id}}\'' in loader_script
    assert "OnlyOffice image ID mismatch after docker load." in loader_script


def test_airgap_onlyoffice_release_metadata_and_loader_verification() -> None:
    shell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.sh").read_text(encoding="utf-8")
    powershell_script = (CODE_ROOT / "scripts" / "build-airgap-bundle.ps1").read_text(encoding="utf-8")
    loader_script = (CODE_ROOT / "scripts" / "load-airgap-images.sh").read_text(encoding="utf-8")

    assert 'export ONLYOFFICE_IMAGE="sewpg-bid/onlyoffice:${TAG}-fontpack-v1"' in shell_script
    assert 'export ONLYOFFICE_BUILD_REVISION="${GIT_SHA}"' in shell_script
    assert 'git -C "${REPO_ROOT}" status --porcelain' in shell_script
    assert 'require_digest_reference "${ONLYOFFICE_SOURCE_IMAGE}"' in shell_script
    assert 'require_digest_reference "${ONLYOFFICE_FONT_BUILDER_SOURCE_IMAGE}"' in shell_script
    assert 'ONLYOFFICE_IMAGE_ID="$(docker image inspect --format \'{{.Id}}\'' in shell_script
    assert '"onlyofficeImageId": "${ONLYOFFICE_IMAGE_ID}"' in shell_script
    assert 'print "ONLYOFFICE_IMAGE=sewpg-bid/onlyoffice:" tag "-fontpack-v1"' in shell_script

    assert '$onlyofficeImage = "sewpg-bid/onlyoffice:$Tag-fontpack-v1"' in powershell_script
    assert "$env:ONLYOFFICE_BUILD_REVISION = $gitSha" in powershell_script
    assert "git -C $repoRoot status --porcelain" in powershell_script
    assert "Assert-DigestReference -Image $OnlyOfficeSourceImage" in powershell_script
    assert "Assert-DigestReference -Image $OnlyOfficeFontBuilderSourceImage" in powershell_script
    assert '$onlyofficeImageId = (& docker image inspect --format "{{.Id}}"' in powershell_script
    assert "onlyofficeImageId = $onlyofficeImageId" in powershell_script
    assert 'ONLYOFFICE_IMAGE=sewpg-bid/onlyoffice:$Tag-fontpack-v1' in powershell_script

    checksum_verify = '"${CHECKSUM_COMMAND[@]}" "${CHECKSUM_INPUT_PATH}"'
    docker_load = 'docker load -i "${IMAGE_TAR}"'
    image_id_verify = "docker image inspect --format '{{.Id}}'"
    assert loader_script.index(checksum_verify) < loader_script.index(docker_load)
    assert loader_script.index(docker_load) < loader_script.index(image_id_verify)
    assert '"onlyofficeImageId"' in loader_script
    assert 're.fullmatch(r"sha256:[0-9a-f]{64}", image_id)' in loader_script
    assert 'image.startswith("sewpg-bid/onlyoffice:")' in loader_script
    assert "len(onlyoffice_images) != 1" in loader_script
    assert '"${ACTUAL_ONLYOFFICE_ID}" != "${EXPECTED_ONLYOFFICE_ID}"' in loader_script


def test_5090_release_scripts_guard_online_builds_and_support_offline_bundle() -> None:
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

    online_guard = 'if [[ "${DEPLOY_MODE}" == "online" ]]; then'
    online_build = 'docker compose "${compose_args[@]}" build --provenance=false'
    assert target_script.rindex(online_guard) < target_script.index(online_build)
    assert '"${build_args[@]}" web fastapi docling-worker opencode onlyoffice' in target_script
    assert 'git -C "${ROOT_DIR}" status --porcelain' in target_script
    assert "--untracked-files=no" not in target_script
    assert 'CURRENT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"' in target_script
    assert '"${CURRENT_SHA}" != "$(git -C "${ROOT_DIR}" rev-parse origin/main)"' in target_script
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


def test_compose_injects_tech_wiki_pdf_extract_env_into_fastapi_and_workers() -> None:
    # R09-B10-01：material_deep_parse 在模块导入时读取这三个变量，
    # fastapi / worker / material-worker 容器必须都能通过 .env 覆盖。
    compose = yaml.safe_load((CODE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    expected = {
        "TECH_WIKI_PDF_EXTRACT_ENABLED": "${TECH_WIKI_PDF_EXTRACT_ENABLED:-true}",
        "TECH_WIKI_EXTRACT_MAX_PAGES": "${TECH_WIKI_EXTRACT_MAX_PAGES:-80}",
        "TECH_WIKI_EXTRACT_OCR_PAGE_CONCURRENCY": "${TECH_WIKI_EXTRACT_OCR_PAGE_CONCURRENCY:-4}",
    }
    for service_name in ("fastapi", "worker", "material-worker"):
        environment = services[service_name]["environment"]
        for key, value in expected.items():
            assert environment[key] == value


def test_env_templates_contain_tech_wiki_pdf_extract_settings() -> None:
    expected = (
        "TECH_WIKI_PDF_EXTRACT_ENABLED=true",
        "TECH_WIKI_EXTRACT_MAX_PAGES=80",
        "TECH_WIKI_EXTRACT_OCR_PAGE_CONCURRENCY=4",
    )
    for template_name in (".env.example", ".env.airgap.example"):
        env_template = (CODE_ROOT / template_name).read_text(encoding="utf-8")
        for setting in expected:
            assert setting in env_template
