"""Run explicitly: pytest tests/azure_functions/python/container_smoke.py. Requires Docker and a Linux ZIP.

The filename intentionally excludes this test from ordinary local pytest runs.
CI runs it as a required stage, where missing Docker is a failure, not a skip.
"""
import os
from pathlib import Path
import uuid

from container_support import docker, extract_package, wait_for_health


def test_packaged_function_runs_in_functions_host(tmp_path):
    archive = Path(os.environ["PACKAGE_ZIP"]).resolve()
    image = os.environ["FUNCTIONS_TEST_IMAGE"]
    diagnostics = Path(os.environ.get("CONTAINER_LOG_DIR", "test-results/container"))
    diagnostics.mkdir(parents=True, exist_ok=True)
    package = tmp_path / "package"
    extract_package(archive, package)
    docker("info")
    docker("pull", "--platform", "linux/amd64", image, timeout=600)
    details = docker("image", "inspect", image)
    (diagnostics / "image.json").write_text(details.stdout)
    container = "platform-functions-test-" + uuid.uuid4().hex
    try:
        docker("run", "--detach", "--name", container,
               "--platform", "linux/amd64",
               "--publish", "127.0.0.1::80",
               "--mount", f"type=bind,source={package},target=/home/site/wwwroot,readonly",
               "--env", "AzureWebJobsScriptRoot=/home/site/wwwroot",
               "--env", "AzureFunctionsJobHost__Logging__Console__IsEnabled=true",
               "--env", "FUNCTIONS_WORKER_RUNTIME=python",
               "--env", "AzureWebJobsSecretStorageType=files",
               image)
        address = docker("port", container, "80/tcp").stdout.strip()
        assert address.startswith("127.0.0.1:"), address
        wait_for_health(container, f"http://{address}/api/health")
    finally:
        # Keep diagnostics even on startup/HTTP failures; always attempt cleanup.
        try:
            logs = docker("logs", container, check=False)
            (diagnostics / "functions-host.log").write_text(logs.stdout + logs.stderr)
            state = docker("inspect", container, check=False)
            (diagnostics / "container.json").write_text(state.stdout + state.stderr)
        finally:
            docker("rm", "--force", container, check=False)
