from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from launcher_core import (
    LauncherError,
    UpdateError,
    check_for_update,
    compose_service_ready,
    docker_available,
    find_project_root,
    load_config,
    perform_update,
    read_version,
    start_compose,
    url_ready,
    wait_until,
)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def info(message: str) -> None:
    print(f"[INFO] {message}")


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def main() -> int:
    print("Crypto Platform Launcher")
    try:
        root = find_project_root(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd())
        version = read_version(root)
        config = load_config(root)
    except LauncherError as exc:
        fail(str(exc))
        return 2

    print(f"Version: {version}\n")
    info(f"Project root: {root}")

    updated = False
    try:
        update_status, manifest = check_for_update(root, config, version)
        if update_status == "not_configured":
            info("Update check skipped: no update manifest URL configured")
        elif update_status == "disabled":
            info("Update check disabled by launcher configuration")
        elif update_status == "current":
            ok("Application is up to date")
        elif update_status == "available" and manifest is not None:
            info(f"Update available: {version} -> {manifest.version}")
            if manifest.release_notes:
                print(f"Release notes: {manifest.release_notes}")
            should_update = manifest.mandatory
            if not should_update:
                try:
                    answer = input("Install this update now? [y/N]: ").strip().lower()
                except EOFError:
                    answer = "n"
                should_update = answer in {"y", "yes"}
            if should_update:
                backup = perform_update(root, manifest, int(config.get("http_timeout_seconds", 10)) * 3)
                ok(f"Update installed. Backup created at: {backup}")
                version = read_version(root)
                updated = True
                print(f"Version: {version}")
                info("Continue startup with the updated project. Restart the launcher if the launcher binary itself changed.")
            else:
                info("Update deferred")
    except UpdateError as exc:
        fail(f"Update check/install failed safely: {exc}")
        info("Continuing with the installed version")

    docker_ok, docker_detail = docker_available()
    if not docker_ok:
        fail(docker_detail)
        return 3
    ok(f"Docker detected ({docker_detail})")

    try:
        start_compose(root, config["docker_compose_file"], build=updated)
    except LauncherError as exc:
        fail(str(exc))
        return 4
    ok("Docker Compose services requested")

    timeout = int(config["startup_timeout_seconds"])
    if not wait_until(lambda: compose_service_ready(root, config["docker_compose_file"], "postgres"), timeout):
        fail("PostgreSQL Compose service did not become healthy")
        return 5
    ok("PostgreSQL ready")

    if not wait_until(lambda: compose_service_ready(root, config["docker_compose_file"], "redis"), timeout):
        fail("Redis Compose service did not become healthy")
        return 6
    ok("Redis ready")

    if not wait_until(lambda: url_ready(config["backend_health_url"]), timeout):
        fail(f"API health check failed: {config['backend_health_url']}")
        return 7
    ok("API ready")

    if not wait_until(lambda: url_ready(config["frontend_url"]), timeout):
        fail(f"Frontend did not become ready: {config['frontend_url']}")
        return 8
    ok("Frontend ready")

    print(f"\nOpening:\n{config['frontend_url']}")
    webbrowser.open(config["frontend_url"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[INFO] Launcher interrupted. Existing Docker services were left unchanged.")
        raise SystemExit(130)
