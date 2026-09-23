"""Utilities for the explicit Docker smoke test; no Azure credentials needed."""
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import zipfile


def docker(*args, timeout=60, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, check=check)


def extract_package(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        required = {"host.json", "function_app.py", "requirements.txt", "src/__init__.py"}
        if not required <= names:
            raise ValueError(f"Missing package files: {sorted(required - names)}")
        if not any(name.startswith(".python_packages/lib/site-packages/") for name in names):
            raise ValueError("Package has no bundled dependencies")
        for name in names:
            if not (destination / name).resolve().is_relative_to(destination):
                raise ValueError(f"Unsafe ZIP path: {name}")
        bundle.extractall(destination)


def wait_for_health(container, url, timeout=180):
    deadline = time.monotonic() + timeout
    last_error = "No HTTP response"
    # Bypass proxies for the local container endpoint.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        state = docker("inspect", "--format", "{{.State.Running}}", container).stdout.strip()
        if state != "true":
            raise RuntimeError("Functions container exited before the health check passed")
        try:
            with client.open(url, timeout=5) as response:
                body = response.read()
                if response.status == 200 and body == b"platform template smoke test":
                    return
                last_error = f"Unexpected response: {response.status}, {body!r}"
        except (urllib.error.URLError, OSError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Functions health check timed out after {timeout}s: {last_error}")
