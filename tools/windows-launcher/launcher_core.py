from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_CONFIG = {
    "frontend_url": "http://localhost:3000",
    "backend_health_url": "http://localhost:8000/health",
    "docker_compose_file": "docker-compose.yml",
    "update_manifest_url": "",
    "update_check_enabled": True,
    "startup_timeout_seconds": 180,
    "http_timeout_seconds": 10,
}

PROTECTED_NAMES = {".env", "launcher-config.json"}
PROTECTED_PREFIXES = {
    ".git",
    "data",
    "postgres_data",
    "redis_data",
    "volumes",
}
REQUIRED_MANIFEST_FIELDS = {"version", "download_url", "sha256"}
MAX_UPDATE_FILES = 20000
MAX_UPDATE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


class LauncherError(RuntimeError):
    pass


class UpdateError(LauncherError):
    pass


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    download_url: str
    sha256: str
    release_notes: str = ""
    mandatory: bool = False


def parse_version(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", text):
        raise ValueError(f"Invalid application version: {value!r}; expected X.Y.Z")
    if text.startswith("v"):
        text = text[1:]
    return tuple(int(p) for p in text.split("."))


def is_newer_version(current: str, candidate: str) -> bool:
    cur = parse_version(current)
    new = parse_version(candidate)
    width = max(len(cur), len(new))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def find_project_root(start: Path | None = None) -> Path:
    env_root = os.environ.get("CRYPTO_PLATFORM_ROOT")
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if start:
        candidates.append(start)
    if getattr(__import__("sys"), "frozen", False):
        candidates.append(Path(__import__("sys").executable).resolve().parent)
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parent)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        for path in (candidate, *candidate.parents):
            if path in seen:
                continue
            seen.add(path)
            if (path / "docker-compose.yml").is_file() and (path / "VERSION").is_file():
                return path
    raise LauncherError("Project root not found. Set CRYPTO_PLATFORM_ROOT or run from the project directory.")


def read_version(project_root: Path) -> str:
    path = project_root / "VERSION"
    if not path.is_file():
        raise LauncherError(f"Missing VERSION file: {path}")
    version = path.read_text(encoding="utf-8").strip()
    parse_version(version)
    return version


def load_config(project_root: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config_path = project_root / "launcher-config.json"
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LauncherError(f"Invalid launcher-config.json: {exc}") from exc
        if not isinstance(loaded, dict):
            raise LauncherError("launcher-config.json must contain a JSON object")
        config.update(loaded)

    env_map = {
        "CRYPTO_PLATFORM_FRONTEND_URL": "frontend_url",
        "CRYPTO_PLATFORM_BACKEND_HEALTH_URL": "backend_health_url",
        "CRYPTO_PLATFORM_COMPOSE_FILE": "docker_compose_file",
        "CRYPTO_PLATFORM_UPDATE_MANIFEST_URL": "update_manifest_url",
        "CRYPTO_PLATFORM_STARTUP_TIMEOUT_SECONDS": "startup_timeout_seconds",
        "CRYPTO_PLATFORM_HTTP_TIMEOUT_SECONDS": "http_timeout_seconds",
    }
    for env_name, key in env_map.items():
        if os.environ.get(env_name):
            value: Any = os.environ[env_name]
            if key.endswith("_seconds"):
                try:
                    value = int(value)
                except ValueError as exc:
                    raise LauncherError(f"{env_name} must be an integer") from exc
            config[key] = value
    if "CRYPTO_PLATFORM_UPDATE_CHECK_ENABLED" in os.environ:
        config["update_check_enabled"] = os.environ["CRYPTO_PLATFORM_UPDATE_CHECK_ENABLED"].strip().lower() not in {
            "0", "false", "no", "off"
        }

    for key in ("frontend_url", "backend_health_url", "docker_compose_file"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise LauncherError(f"Launcher configuration field {key!r} must be a non-empty string")
    for key in ("startup_timeout_seconds", "http_timeout_seconds"):
        if not isinstance(config.get(key), int) or config[key] <= 0:
            raise LauncherError(f"Launcher configuration field {key!r} must be a positive integer")
    return config


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def docker_available() -> tuple[bool, str]:
    if not command_exists("docker"):
        return False, "Docker CLI was not found in PATH"
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Docker is unavailable: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, f"Docker daemon is not ready: {detail or 'docker info failed'}"
    return True, result.stdout.strip() or "ready"


def compose_command() -> list[str]:
    if command_exists("docker"):
        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return ["docker", "compose"]
        except (OSError, subprocess.SubprocessError):
            pass
    if command_exists("docker-compose"):
        return ["docker-compose"]
    raise LauncherError("Docker Compose was not found. Install Docker Desktop with Compose support.")


def start_compose(project_root: Path, compose_file: str, *, build: bool = False) -> None:
    compose_path = (project_root / compose_file).resolve()
    try:
        compose_path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise LauncherError("docker_compose_file must remain inside the project root") from exc
    if not compose_path.is_file():
        raise LauncherError(f"Docker Compose file not found: {compose_path}")
    cmd = [*compose_command(), "-f", str(compose_path), "up", "-d"]
    if build:
        cmd.append("--build")
    result = subprocess.run(cmd, cwd=project_root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise LauncherError(f"Docker Compose startup failed: {(result.stderr or result.stdout).strip()}")



def compose_service_ready(project_root: Path, compose_file: str, service: str) -> bool:
    compose_path = (project_root / compose_file).resolve()
    cmd = [*compose_command(), "-f", str(compose_path), "ps", "-q", service]
    try:
        result = subprocess.run(cmd, cwd=project_root, text=True, capture_output=True, timeout=10, check=False)
        container_id = result.stdout.strip()
        if result.returncode != 0 or not container_id:
            return False
        inspect = subprocess.run(
            ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", container_id],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return inspect.returncode == 0 and inspect.stdout.strip() in {"healthy", "running"}
    except (OSError, subprocess.SubprocessError, LauncherError):
        return False


def url_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoPlatformLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def port_ready(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until(check: Callable[[], bool], timeout_seconds: int, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return bool(check())


def validate_https_url(url: str, *, allow_http_localhost: bool = False) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return
    if allow_http_localhost and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    raise UpdateError("Update URLs must use HTTPS")


def validate_manifest(payload: Any) -> UpdateManifest:
    if not isinstance(payload, dict):
        raise UpdateError("Update manifest must be a JSON object")
    missing = REQUIRED_MANIFEST_FIELDS.difference(payload)
    if missing:
        raise UpdateError(f"Update manifest missing required field(s): {', '.join(sorted(missing))}")
    version = payload["version"]
    download_url = payload["download_url"]
    digest = payload["sha256"]
    release_notes = payload.get("release_notes", "")
    mandatory = payload.get("mandatory", False)
    if not isinstance(version, str):
        raise UpdateError("Manifest version must be a string")
    try:
        parse_version(version)
    except ValueError as exc:
        raise UpdateError(str(exc)) from exc
    if not isinstance(download_url, str):
        raise UpdateError("Manifest download_url must be a string")
    validate_https_url(download_url)
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise UpdateError("Manifest sha256 must be a 64-character hexadecimal SHA-256 digest")
    if not isinstance(release_notes, str):
        raise UpdateError("Manifest release_notes must be a string")
    if not isinstance(mandatory, bool):
        raise UpdateError("Manifest mandatory must be a boolean")
    return UpdateManifest(version, download_url, digest.lower(), release_notes, mandatory)


def fetch_manifest(url: str, timeout_seconds: int = 10) -> UpdateManifest:
    validate_https_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoPlatformLauncher/1.0", "Accept": "application/json"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds, context=context) as response:
            validate_https_url(response.geturl())
            if response.status != 200:
                raise UpdateError(f"Manifest request returned HTTP {response.status}")
            raw = response.read(1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Unable to fetch update manifest: {exc}") from exc
    if len(raw) > 1024 * 1024:
        raise UpdateError("Update manifest is unexpectedly large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Malformed update manifest: {exc}") from exc
    return validate_manifest(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> bool:
    return sha256_file(path).lower() == expected.lower()


def download_update(url: str, destination: Path, timeout_seconds: int = 30) -> Path:
    validate_https_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoPlatformLauncher/1.0"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds, context=context) as response, partial.open("wb") as output:
            validate_https_url(response.geturl())
            if response.status != 200:
                raise UpdateError(f"Update download returned HTTP {response.status}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        partial.replace(destination)
        return destination
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _safe_member_destination(base: Path, name: str) -> Path:
    if not name or "\x00" in name:
        raise UpdateError("Update ZIP contains an invalid member name")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in f"/{normalized}":
        raise UpdateError(f"Unsafe path in update ZIP: {name}")
    target = (base / normalized).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise UpdateError(f"Unsafe path in update ZIP: {name}") from exc
    return target


def safe_extract_zip(zip_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if not members:
                raise UpdateError("Update ZIP is empty")
            if len(members) > MAX_UPDATE_FILES:
                raise UpdateError("Update ZIP contains too many files")
            total_size = sum(info.file_size for info in members)
            if total_size > MAX_UPDATE_UNCOMPRESSED_BYTES:
                raise UpdateError("Update ZIP expands beyond the allowed size limit")
            for info in members:
                target = _safe_member_destination(destination, info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise UpdateError(f"Symbolic links are not allowed in update ZIPs: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise UpdateError("Downloaded update package is not a valid ZIP file") from exc
    return normalize_update_root(destination)


def normalize_update_root(extracted: Path) -> Path:
    if (extracted / "VERSION").is_file() and (extracted / "docker-compose.yml").is_file():
        return extracted
    children = [p for p in extracted.iterdir() if p.is_dir()]
    files = [p for p in extracted.iterdir() if p.is_file()]
    if len(children) == 1 and not files:
        child = children[0]
        if (child / "VERSION").is_file() and (child / "docker-compose.yml").is_file():
            return child
    raise UpdateError("Update ZIP does not contain the expected Crypto Platform project structure")


def is_protected_relative(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if relative.name in PROTECTED_NAMES:
        return True
    if relative.name.startswith(".env") and relative.name != ".env.example":
        return True
    if relative.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        return True
    if relative.name.lower() in {"credentials.json", "secrets.json"}:
        return True
    return parts[0] in PROTECTED_PREFIXES


def iter_update_files(source_root: Path) -> Iterable[tuple[Path, Path]]:
    for source in source_root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if is_protected_relative(relative):
            continue
        yield source, relative


def apply_update(source_root: Path, project_root: Path, backup_root: Path) -> None:
    project_root = project_root.resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    try:
        for source, relative in iter_update_files(source_root):
            target = project_root / relative
            backup = backup_root / relative
            if target.exists() and target.is_file():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
    except Exception as exc:
        for relative in reversed(copied):
            target = project_root / relative
            backup = backup_root / relative
            try:
                if backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                pass
        raise UpdateError(f"Update failed and rollback was attempted: {exc}") from exc


def check_for_update(project_root: Path, config: dict[str, Any], current_version: str) -> tuple[str, UpdateManifest | None]:
    if not config.get("update_check_enabled", True):
        return "disabled", None
    manifest_url = str(config.get("update_manifest_url") or os.environ.get("CRYPTO_PLATFORM_UPDATE_MANIFEST_URL", "")).strip()
    if not manifest_url:
        return "not_configured", None
    manifest = fetch_manifest(manifest_url, int(config.get("http_timeout_seconds", 10)))
    return ("available", manifest) if is_newer_version(current_version, manifest.version) else ("current", manifest)


def perform_update(project_root: Path, manifest: UpdateManifest, timeout_seconds: int = 30) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="crypto-platform-update-"))
    try:
        package = temp_dir / "update.zip"
        download_update(manifest.download_url, package, timeout_seconds)
        if not verify_sha256(package, manifest.sha256):
            raise UpdateError("Downloaded update package failed SHA-256 verification")
        extracted_root = safe_extract_zip(package, temp_dir / "extracted")
        package_version = read_version(extracted_root)
        if package_version != manifest.version:
            raise UpdateError(
                f"Manifest/package version mismatch: manifest={manifest.version}, package={package_version}"
            )
        backup = project_root / ".launcher-backups" / f"pre-{manifest.version}-{int(time.time())}"
        apply_update(extracted_root, project_root, backup)
        return backup
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
