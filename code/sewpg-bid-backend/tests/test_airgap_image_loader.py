import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


CODE_ROOT = Path(__file__).resolve().parents[2]
LOADER_SCRIPT = CODE_ROOT / "scripts" / "load-airgap-images.sh"
EXPECTED_IMAGE_ID = "sha256:" + "1" * 64
ONLYOFFICE_IMAGE = "sewpg-bid/onlyoffice:offline-test-fontpack-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest_and_checksums(
    bundle_root: Path,
    selected_tar: Path,
    manifest: dict[str, object],
) -> None:
    manifest_path = bundle_root / "bundle-manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    (bundle_root / "SHA256SUMS").write_text(
        "\n".join(
            (
                f"{_sha256(manifest_path)}  bundle-manifest.json",
                f"{_sha256(selected_tar)}  images/{selected_tar.name}",
            )
        )
        + "\n",
        encoding="ascii",
    )


def _create_bundle() -> tuple[Path, Path, Path, dict[str, object]]:
    bundle_root = Path(tempfile.mkdtemp(prefix="onlyoffice-loader-test-"))
    (bundle_root / "docker-compose.yml").touch()
    shutil.copy2(LOADER_SCRIPT, bundle_root / "load-airgap-images.sh")

    images_dir = bundle_root / "images"
    images_dir.mkdir()
    old_tar = images_dir / "sewpg-bid-images-offline-old.tar"
    selected_tar = images_dir / "sewpg-bid-images-offline-test.tar"
    old_tar.write_bytes(b"old bundle")
    selected_tar.write_bytes(b"selected bundle")

    manifest: dict[str, object] = {
        "bundleFile": selected_tar.name,
        "onlyofficeImageId": EXPECTED_IMAGE_ID,
        "images": [ONLYOFFICE_IMAGE],
    }
    _write_manifest_and_checksums(bundle_root, selected_tar, manifest)

    fake_bin = bundle_root / "fake-bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "load" && "$2" == "-i" ]]; then
  printf '%s\n' "$3" > "${TEST_DOCKER_LOAD_LOG}"
  exit 0
fi
if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  printf '%s\n' "${TEST_ACTUAL_IMAGE_ID}"
  exit 0
fi
exit 2
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    return bundle_root, selected_tar, old_tar, manifest


def _run_loader(
    bundle_root: Path,
    *arguments: str,
    actual_image_id: str = EXPECTED_IMAGE_ID,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PATH": f"{bundle_root / 'fake-bin'}:{os.environ['PATH']}",
        "TEST_ACTUAL_IMAGE_ID": actual_image_id,
        "TEST_DOCKER_LOAD_LOG": str(bundle_root / "docker-load.log"),
    }
    return subprocess.run(
        ["bash", str(bundle_root / "load-airgap-images.sh"), *arguments],
        cwd=bundle_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_loader_uses_manifest_tar_when_multiple_archives_exist() -> None:
    bundle_root, selected_tar, _, _ = _create_bundle()
    try:
        completed = _run_loader(bundle_root)

        assert completed.returncode == 0, completed.stderr
        assert (bundle_root / "docker-load.log").read_text(encoding="utf-8").strip() == str(
            selected_tar
        )
        assert f"OnlyOffice image verified: {ONLYOFFICE_IMAGE}" in completed.stdout
    finally:
        shutil.rmtree(bundle_root)


def test_loader_rejects_tar_that_does_not_match_manifest() -> None:
    bundle_root, _, old_tar, _ = _create_bundle()
    try:
        completed = _run_loader(bundle_root, str(old_tar))

        assert completed.returncode == 1
        assert "Requested tar does not match bundle-manifest.json." in completed.stderr
        assert not (bundle_root / "docker-load.log").exists()
    finally:
        shutil.rmtree(bundle_root)


def test_loader_requires_checksum_and_complete_manifest_before_load() -> None:
    bundle_root, selected_tar, _, manifest = _create_bundle()
    try:
        (bundle_root / "SHA256SUMS").unlink()
        missing_checksum = _run_loader(bundle_root, str(selected_tar))
        assert missing_checksum.returncode == 1
        assert "Incomplete offline bundle" in missing_checksum.stderr
        assert not (bundle_root / "docker-load.log").exists()

        manifest.pop("onlyofficeImageId")
        _write_manifest_and_checksums(bundle_root, selected_tar, manifest)
        incomplete_manifest = _run_loader(bundle_root, str(selected_tar))
        assert incomplete_manifest.returncode == 1
        assert "onlyofficeImageId is missing or invalid" in incomplete_manifest.stderr
        assert not (bundle_root / "docker-load.log").exists()
    finally:
        shutil.rmtree(bundle_root)


def test_loader_rejects_loaded_onlyoffice_image_id_mismatch() -> None:
    bundle_root, _, _, _ = _create_bundle()
    try:
        completed = _run_loader(
            bundle_root,
            actual_image_id="sha256:" + "2" * 64,
        )

        assert completed.returncode == 1
        assert "OnlyOffice image ID mismatch after docker load." in completed.stderr
        assert (bundle_root / "docker-load.log").exists()
    finally:
        shutil.rmtree(bundle_root)


def test_loader_accepts_windows_crlf_checksum_list() -> None:
    bundle_root, selected_tar, _, _ = _create_bundle()
    try:
        checksum_path = bundle_root / "SHA256SUMS"
        checksum_path.write_bytes(checksum_path.read_bytes().replace(b"\n", b"\r\n"))
        completed = _run_loader(bundle_root)

        assert completed.returncode == 0, completed.stderr
        assert (bundle_root / "docker-load.log").read_text(encoding="utf-8").strip() == str(
            selected_tar
        )
    finally:
        shutil.rmtree(bundle_root)
