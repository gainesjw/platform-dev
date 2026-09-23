"""Exercise Docker test failure handling without requiring a Docker daemon."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import zipfile

import pytest

import container_smoke
import container_support as support


def archive_with_files(path, extra=()):
    with zipfile.ZipFile(path, "w") as bundle:
        for name in ("host.json", "function_app.py", "requirements.txt", "src/__init__.py",
                     ".python_packages/lib/site-packages/dependency.py", *extra):
            bundle.writestr(name, "fixture")


def test_extracts_artifact_dependencies(tmp_path):
    archive = tmp_path / "app.zip"
    archive_with_files(archive)
    support.extract_package(archive, tmp_path / "package")
    assert (tmp_path / "package/.python_packages/lib/site-packages/dependency.py").is_file()


def test_rejects_zip_traversal(tmp_path):
    archive = tmp_path / "app.zip"
    archive_with_files(archive, ["../outside.py"])
    with pytest.raises(ValueError, match="Unsafe ZIP path"):
        support.extract_package(archive, tmp_path / "package")
    assert not (tmp_path / "outside.py").exists()


def test_missing_dependencies_fail_before_docker(tmp_path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in ("host.json", "function_app.py", "requirements.txt", "src/__init__.py"):
            bundle.writestr(name, "fixture")
    with pytest.raises(ValueError, match="no bundled dependencies"):
        support.extract_package(archive, tmp_path / "package")


def test_health_check_detects_container_exit(monkeypatch):
    monkeypatch.setattr(support, "docker", MagicMock(return_value=SimpleNamespace(stdout="false")))
    with pytest.raises(RuntimeError, match="exited"):
        support.wait_for_health("fixture", "http://127.0.0.1:1234/api/health")


@pytest.mark.parametrize("body,passes", [(b"platform template smoke test", True), (b"wrong app", False)])
def test_health_check_requires_expected_response(monkeypatch, body, passes):
    monkeypatch.setattr(support, "docker", MagicMock(return_value=SimpleNamespace(stdout="true")))
    response = MagicMock()
    response.__enter__.return_value = SimpleNamespace(status=200, read=lambda: body)
    client = MagicMock()
    client.open.return_value = response
    monkeypatch.setattr(support.urllib.request, "build_opener", MagicMock(return_value=client))
    monkeypatch.setattr(support.time, "monotonic", MagicMock(side_effect=[0, 0, 181]))
    monkeypatch.setattr(support.time, "sleep", MagicMock())
    if passes:
        support.wait_for_health("fixture", "http://127.0.0.1:1234/api/health")
    else:
        with pytest.raises(RuntimeError, match="Unexpected response"):
            support.wait_for_health("fixture", "http://127.0.0.1:1234/api/health")


def test_smoke_retains_logs_and_removes_container_when_health_fails(tmp_path, monkeypatch):
    archive = tmp_path / "app.zip"
    archive_with_files(archive)
    monkeypatch.setenv("PACKAGE_ZIP", str(archive))
    monkeypatch.setenv("FUNCTIONS_TEST_IMAGE", "test-image")
    monkeypatch.setenv("CONTAINER_LOG_DIR", str(tmp_path / "logs"))

    def fake_docker(*args, **kwargs):
        output = "127.0.0.1:1234" if args[0] == "port" else "host diagnostics"
        return SimpleNamespace(stdout=output, stderr="")

    docker = MagicMock(side_effect=fake_docker)
    monkeypatch.setattr(container_smoke, "docker", docker)
    monkeypatch.setattr(container_smoke, "wait_for_health", MagicMock(side_effect=RuntimeError("unhealthy")))
    with pytest.raises(RuntimeError, match="unhealthy"):
        container_smoke.test_packaged_function_runs_in_functions_host(tmp_path)
    assert (tmp_path / "logs/functions-host.log").read_text() == "host diagnostics"
    assert docker.call_args.args[:2] == ("rm", "--force")
    run_args = next(call.args for call in docker.call_args_list if call.args[0] == "run")
    assert "linux/amd64" in run_args
    assert "127.0.0.1::80" in run_args
    assert any("target=/home/site/wwwroot,readonly" in arg for arg in run_args)
