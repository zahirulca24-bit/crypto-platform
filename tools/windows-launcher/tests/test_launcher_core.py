import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from launcher_core import (  # noqa: E402
    UpdateError,
    apply_update,
    check_for_update,
    is_newer_version,
    load_config,
    safe_extract_zip,
    validate_https_url,
    validate_manifest,
    verify_sha256,
    wait_until,
)


def project(tmp_path: Path) -> Path:
    (tmp_path / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return tmp_path


def test_version_comparison():
    assert is_newer_version("0.3.0", "0.3.1")
    with pytest.raises(ValueError):
        is_newer_version("0.3", "0.3.1")
    assert not is_newer_version("0.3.1", "0.3.1")
    assert not is_newer_version("1.0.0", "0.9.9")


def test_manifest_validation():
    manifest = validate_manifest({
        "version": "0.3.1",
        "download_url": "https://example.com/release.zip",
        "sha256": "a" * 64,
        "release_notes": "notes",
        "mandatory": False,
    })
    assert manifest.version == "0.3.1"
    assert manifest.sha256 == "a" * 64


@pytest.mark.parametrize("payload", [
    {},
    {"version": "x", "download_url": "https://example.com/a.zip", "sha256": "a" * 64},
    {"version": "1.0.0", "download_url": "http://example.com/a.zip", "sha256": "a" * 64},
    {"version": "1.0.0", "download_url": "https://example.com/a.zip", "sha256": "bad"},
])
def test_malformed_manifest_rejected(payload):
    with pytest.raises(UpdateError):
        validate_manifest(payload)


def test_https_validation():
    validate_https_url("https://example.com/update.json")
    with pytest.raises(UpdateError):
        validate_https_url("http://example.com/update.json")


def test_sha256_verification(tmp_path: Path):
    payload = tmp_path / "payload.zip"
    payload.write_bytes(b"safe payload")
    digest = hashlib.sha256(b"safe payload").hexdigest()
    assert verify_sha256(payload, digest)
    assert not verify_sha256(payload, "0" * 64)


def test_zip_slip_rejected(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(UpdateError):
        safe_extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "escape.txt").exists()


def test_configuration_loading_and_env_override(tmp_path: Path, monkeypatch):
    root = project(tmp_path)
    (root / "launcher-config.json").write_text(json.dumps({"frontend_url": "http://localhost:3333"}), encoding="utf-8")
    monkeypatch.setenv("CRYPTO_PLATFORM_STARTUP_TIMEOUT_SECONDS", "42")
    config = load_config(root)
    assert config["frontend_url"] == "http://localhost:3333"
    assert config["startup_timeout_seconds"] == 42
    assert config["backend_health_url"] == "http://localhost:8000/health"


def test_no_update_when_manifest_not_configured(tmp_path: Path):
    root = project(tmp_path)
    config = load_config(root)
    status, manifest = check_for_update(root, config, "0.3.0")
    assert status == "not_configured"
    assert manifest is None


def test_newer_version_detection_via_manifest_validation():
    manifest = validate_manifest({
        "version": "0.4.0",
        "download_url": "https://example.com/update.zip",
        "sha256": "b" * 64,
    })
    assert is_newer_version("0.3.0", manifest.version)


def test_service_readiness_helper_logic():
    calls = iter([False, False, True])
    assert wait_until(lambda: next(calls), timeout_seconds=1, interval=0)


def test_update_preserves_local_secret_files(tmp_path: Path):
    target = tmp_path / "project"
    source = tmp_path / "source"
    backup = tmp_path / "backup"
    target.mkdir()
    source.mkdir()
    (target / ".env").write_text("SECRET=local\n", encoding="utf-8")
    (target / ".env.local").write_text("TOKEN=local\n", encoding="utf-8")
    (target / "launcher-config.json").write_text('{"local": true}', encoding="utf-8")
    (target / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=release\n", encoding="utf-8")
    (source / ".env.local").write_text("TOKEN=release\n", encoding="utf-8")
    (source / "launcher-config.json").write_text('{"local": false}', encoding="utf-8")
    (source / "VERSION").write_text("0.3.1\n", encoding="utf-8")

    apply_update(source, target, backup)

    assert (target / ".env").read_text(encoding="utf-8") == "SECRET=local\n"
    assert (target / ".env.local").read_text(encoding="utf-8") == "TOKEN=local\n"
    assert json.loads((target / "launcher-config.json").read_text(encoding="utf-8")) == {"local": True}
    assert (target / "VERSION").read_text(encoding="utf-8").strip() == "0.3.1"
