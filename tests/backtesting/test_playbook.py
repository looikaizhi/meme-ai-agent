from __future__ import annotations

import tarfile
from pathlib import Path

import httpx
import pytest
import respx

from memedog.backtesting.playbook import (
    PLAYBOOK_API_BASE_URL,
    PlaybookAPIError,
    PlaybookClient,
    UnsafePlaybookError,
    assert_safe_backtest_playbook,
    build_playbook_archive,
    mask_access_key,
)


def test_mask_access_key_hides_middle() -> None:
    assert mask_access_key("abcd1234wxyz") == "abcd...wxyz"
    assert mask_access_key("short") == "*****"


def test_build_playbook_archive_contains_only_upload_allowed_paths(tmp_path: Path) -> None:
    playbook_dir = tmp_path / "pkg"
    (playbook_dir / "src").mkdir(parents=True)
    (playbook_dir / "manifest.yaml").write_text("name: demo\n", encoding="utf-8")
    (playbook_dir / "backtest.yaml").write_text("venue: {}\n", encoding="utf-8")
    (playbook_dir / "src" / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (playbook_dir / "README.md").write_text("not uploaded\n", encoding="utf-8")
    (playbook_dir / "tests").mkdir()
    (playbook_dir / "tests" / "test_demo.py").write_text("pass\n", encoding="utf-8")

    archive_path = build_playbook_archive(playbook_dir, tmp_path / "pkg.tar.gz")

    with tarfile.open(archive_path, "r:gz") as archive:
        names = sorted(archive.getnames())

    assert names == ["README.md", "backtest.yaml", "manifest.yaml", "src/main.py"]


def test_build_playbook_archive_excludes_python_cache_files(tmp_path: Path) -> None:
    playbook_dir = tmp_path / "pkg"
    (playbook_dir / "src" / "__pycache__").mkdir(parents=True)
    (playbook_dir / "manifest.yaml").write_text("name: demo\n", encoding="utf-8")
    (playbook_dir / "README.md").write_text("readme\n", encoding="utf-8")
    (playbook_dir / "src" / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (playbook_dir / "src" / "__pycache__" / "main.pyc").write_bytes(b"binary")

    archive_path = build_playbook_archive(playbook_dir, tmp_path / "pkg.tar.gz")

    with tarfile.open(archive_path, "r:gz") as archive:
        names = sorted(archive.getnames())

    assert names == ["README.md", "manifest.yaml", "src/main.py"]


def test_build_playbook_archive_requires_manifest_and_main(tmp_path: Path) -> None:
    playbook_dir = tmp_path / "pkg"
    playbook_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        build_playbook_archive(playbook_dir, tmp_path / "pkg.tar.gz")


def test_assert_safe_backtest_playbook_accepts_signal_only_package(tmp_path: Path) -> None:
    playbook_dir = tmp_path / "pkg"
    playbook_dir.mkdir()
    (playbook_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "backtest_support: full",
                "runtime_profile: deterministic",
                "execution_mode: signal_only",
                "follow_trade_supported: false",
            ]
        ),
        encoding="utf-8",
    )

    assert_safe_backtest_playbook(playbook_dir)


def test_assert_safe_backtest_playbook_rejects_follow_trade(tmp_path: Path) -> None:
    playbook_dir = tmp_path / "pkg"
    playbook_dir.mkdir()
    (playbook_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "backtest_support: full",
                "runtime_profile: deterministic",
                "execution_mode: follow_trade",
                "follow_trade_supported: true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(UnsafePlaybookError, match="signal_only"):
        assert_safe_backtest_playbook(playbook_dir)


def test_playbook_client_upload_run_and_poll_sends_access_key(tmp_path: Path) -> None:
    archive_path = tmp_path / "pkg.tar.gz"
    archive_path.write_bytes(b"fake")

    with respx.mock(base_url=PLAYBOOK_API_BASE_URL) as router:
        upload_route = router.post("/api/v1/playbook/upload").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "data": {
                        "strategy_id": "strategy-1",
                        "draft_id": "draft-1",
                        "status": "temporary",
                    },
                    "msg": "",
                },
            )
        )
        run_route = router.post("/api/v1/playbook/run").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "data": {
                        "run_id": "run-1",
                        "version_id": "draft-1",
                        "status": "pending",
                    },
                    "msg": "",
                },
            )
        )
        poll_route = router.get("/api/v1/playbook/run").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "data": {
                        "run_id": "run-1",
                        "status": "completed",
                        "metrics_output": {"win_rate": 0.5},
                    },
                    "msg": "",
                },
            )
        )

        with PlaybookClient("secret-access-key") as client:
            uploaded = client.upload_package(archive_path)
            dispatched = client.start_run(uploaded["draft_id"])
            completed = client.poll_run(dispatched["run_id"], poll_sec=0, timeout_sec=1)

    assert uploaded["draft_id"] == "draft-1"
    assert completed["status"] == "completed"
    assert upload_route.calls[0].request.headers["ACCESS-KEY"] == "secret-access-key"
    assert run_route.calls[0].request.headers["ACCESS-KEY"] == "secret-access-key"
    assert poll_route.calls[0].request.url.params["run_id"] == "run-1"


def test_playbook_client_raises_on_api_error(tmp_path: Path) -> None:
    archive_path = tmp_path / "pkg.tar.gz"
    archive_path.write_bytes(b"fake")

    with respx.mock(base_url=PLAYBOOK_API_BASE_URL) as router:
        router.post("/api/v1/playbook/upload").mock(
            return_value=httpx.Response(422, json={"detail": {"errors": ["bad package"]}})
        )

        with PlaybookClient("secret-access-key") as client:
            with pytest.raises(PlaybookAPIError, match="422"):
                client.upload_package(archive_path)
