"""Bitget GetAgent Playbook upload/run helpers."""
from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any

import httpx
import yaml

PLAYBOOK_API_BASE_URL = "https://api.bitget.com"
ALLOWED_PACKAGE_TOP_LEVEL = {"README.md", "manifest.yaml", "backtest.yaml", "src"}


class PlaybookAPIError(RuntimeError):
    """Raised when the Bitget Playbook API returns an error response."""


class UnsafePlaybookError(RuntimeError):
    """Raised when a Playbook package could trade live or follow orders."""


def mask_access_key(access_key: str) -> str:
    """Return a log-safe representation of a Bitget access key."""
    if len(access_key) <= 8:
        return "*" * len(access_key)
    return f"{access_key[:4]}...{access_key[-4:]}"


def assert_safe_backtest_playbook(playbook_dir: Path) -> None:
    """Refuse hosted runs unless the package is paper/backtest only."""
    manifest_path = playbook_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("backtest_support") != "full":
        errors.append("backtest_support must be full")
    if manifest.get("runtime_profile") != "deterministic":
        errors.append("runtime_profile must be deterministic")
    if manifest.get("execution_mode") != "signal_only":
        errors.append("execution_mode must be signal_only")
    if manifest.get("follow_trade_supported") is not False:
        errors.append("follow_trade_supported must be false")
    if errors:
        raise UnsafePlaybookError("; ".join(errors))


def build_playbook_archive(playbook_dir: Path, output_path: Path | None = None) -> Path:
    """Create a validator-friendly Playbook tar.gz archive.

    The hosted upload endpoint accepts only manifest.yaml, optional
    backtest.yaml, and files under src/**.
    """
    playbook_dir = playbook_dir.resolve()
    if output_path is None:
        tmp = NamedTemporaryFile(
            prefix=f"{playbook_dir.name}-",
            suffix=".tar.gz",
            delete=False,
        )
        tmp.close()
        output_path = Path(tmp.name)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    required = [playbook_dir / "manifest.yaml", playbook_dir / "src" / "main.py"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Playbook package missing required files: {missing}")

    with tarfile.open(output_path, "w:gz") as archive:
        for path in sorted(playbook_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = PurePosixPath(path.relative_to(playbook_dir).as_posix())
            if rel.parts[0] not in ALLOWED_PACKAGE_TOP_LEVEL:
                continue
            if "__pycache__" in rel.parts or path.suffix == ".pyc":
                continue
            if rel.parts[0] == "src" or rel.name in {
                "README.md",
                "manifest.yaml",
                "backtest.yaml",
            }:
                archive.add(path, arcname=rel.as_posix())

    return output_path


class PlaybookClient:
    """Small synchronous client for the GetAgent Playbook control plane."""

    def __init__(
        self,
        access_key: str,
        *,
        base_url: str = PLAYBOOK_API_BASE_URL,
        timeout_sec: float = 30.0,
    ) -> None:
        if not access_key:
            raise ValueError("A Bitget Playbook ACCESS-KEY is required")
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_sec,
            headers={"ACCESS-KEY": access_key},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PlaybookClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def upload_package(self, archive_path: Path) -> dict[str, Any]:
        with archive_path.open("rb") as fh:
            response = self._client.post(
                "/api/v1/playbook/upload",
                files={"package": (archive_path.name, fh, "application/gzip")},
            )
        return self._json_or_error(response)

    def start_run(self, version_id: str) -> dict[str, Any]:
        response = self._client.post(
            "/api/v1/playbook/run",
            json={"version_id": version_id},
        )
        return self._json_or_error(response)

    def get_run(self, run_id: str) -> dict[str, Any]:
        response = self._client.get("/api/v1/playbook/run", params={"run_id": run_id})
        return self._json_or_error(response)

    def poll_run(
        self,
        run_id: str,
        *,
        poll_sec: float = 5.0,
        timeout_sec: float = 300.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_sec
        while True:
            payload = self.get_run(run_id)
            if payload.get("status") in {"completed", "failed"}:
                return payload
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Playbook run {run_id} did not finish within {timeout_sec}s")
            time.sleep(poll_sec)

    @staticmethod
    def _json_or_error(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"detail": response.text}
        if response.status_code >= 400:
            raise PlaybookAPIError(
                f"Playbook API returned {response.status_code}: {payload}"
            )
        if not isinstance(payload, dict):
            raise PlaybookAPIError(f"Playbook API returned non-object JSON: {payload}")
        if payload.get("code") == "200" and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload
