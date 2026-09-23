"""Reusable Linux Python Azure Functions deployment checks.

Standard library only. Run with an authenticated Azure CLI (for example AzureCLI@2).
No app settings are changed by preflight or readiness checks.
"""

import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


def required_env(name):
    value = os.environ.get(name)
    require(value and not value.startswith("$("), f"Missing pipeline environment variable: {name}")
    return value


def resource_fields(value):
    """Accept both flattened CLI resources and ARM properties envelopes."""
    require(isinstance(value, dict), "Expected an Azure resource JSON object")
    properties = value.get("properties")
    if isinstance(properties, dict):
        return {**value, **properties}
    return value


def required_field(value, name, command):
    require(name in value and value[name] is not None,
            f"az functionapp {command} response is missing required field '{name}' "
            f"(also checked properties.{name}); check the target resource and Azure CLI response schema")
    return value[name]


def az(*args):
    app_name = required_env("FUNCTION_APP_NAME")
    resource_group = required_env("RESOURCE_GROUP_NAME")
    operation = " ".join(args[:3] if args[:2] == ("config", "appsettings") else args[:2])
    print(f"Checking Azure: functionapp {operation}", flush=True)
    result = subprocess.run(
        ["az", "functionapp", *args,
         "--name", app_name,
         "--resource-group", resource_group,
         "--only-show-errors", "-o", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        # Never print CLI output: settings and host keys can contain secrets.
        raise RuntimeError(f"Azure CLI functionapp {operation} failed; check service connection permissions and app availability")
    value = json.loads(result.stdout)
    if args in (("show",), ("config", "show"), ("keys", "list")):
        return resource_fields(value)
    if args == ("function", "list"):
        if isinstance(value, dict):
            value = required_field(value, "value", "function list")
        require(isinstance(value, list), "Expected a list from az functionapp function list")
        return [resource_fields(item) for item in value]
    return value


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preflight(*, require_managed_identity=False, require_host_storage=False):
    """Return settings after validating runtime and explicitly requested capabilities."""
    python_version = required_env("PYTHON_VERSION")
    app = az("show")
    require("linux" in app.get("kind", "").lower(), "Expected an existing Linux Function App")
    require(required_field(app, "state", "show") == "Running", "Function App must be started before deployment")
    if require_managed_identity:
        require((app.get("identity") or {}).get("type", "None") != "None", "Enable a managed identity on the Function App")
    flex = os.environ.get("IS_FLEX_CONSUMPTION", "false").lower() == "true"
    app_runtime = (app.get("functionAppConfig") or {}).get("runtime") or {}
    if flex:
        require(bool(app_runtime), "Pipeline targets Flex Consumption but functionAppConfig.runtime is missing")
        language = app_runtime.get("name")
        version = app_runtime.get("version")
        print(f"Configured Flex runtime: {language} {version}; expected python {python_version}", flush=True)
        require(language == "python" and version == python_version,
                f"Flex runtime mismatch: expected python {python_version}, received {language} {version}; "
                "align pythonVersion with the Function App runtime")
    else:
        require(not app_runtime, "App exposes functionAppConfig.runtime; configure the pipeline for Flex Consumption")
        runtime = az("config", "show").get("linuxFxVersion") or ""
        require(runtime.lower() == f"python|{python_version}",
                f"Runtime mismatch: expected PYTHON|{python_version}, received {runtime or '(empty)'}; "
                "check the hosting plan and align pythonVersion with the Function App runtime")
    raw_settings = az("config", "appsettings", "list")
    require(isinstance(raw_settings, list), "Expected a list from az functionapp config appsettings list")
    settings = {}
    for item in raw_settings:
        require(isinstance(item, dict) and "name" in item and "value" in item,
                "App settings response contains an entry missing 'name' or 'value'; values were not logged")
        settings[item["name"]] = item["value"] or ""
    # Flex configures its language in functionAppConfig and manages the host
    # version itself; legacy worker/runtime app settings are not required.
    if not flex:
        require(settings.get("FUNCTIONS_WORKER_RUNTIME") == "python", "FUNCTIONS_WORKER_RUNTIME must be python")
        require(settings.get("FUNCTIONS_EXTENSION_VERSION", "").lstrip("~").split(".")[0] == "4",
                "FUNCTIONS_EXTENSION_VERSION must select Functions v4")
    if require_host_storage:
        require(settings.get("AzureWebJobsStorage") or settings.get("AzureWebJobsStorage__accountName")
                or settings.get("AzureWebJobsStorage__blobServiceUri"), "Configure AzureWebJobsStorage for the Functions host")
    print("Preflight passed: runtime and requested capabilities configured")
    return settings


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the master key to a redirected endpoint.
        return None


def host_request(hostname, key, path, payload=None):
    request = Request(
        f"https://{hostname}{path}",
        headers={"x-functions-key": key, "Content-Type": "application/json"},
        data=None if payload is None else json.dumps(payload).encode(),
    )
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        body = response.read()
        return response.status, json.loads(body) if body else None


def wait_until(check, description, timeout=300):
    deadline = time.monotonic() + timeout
    while True:
        if check():
            print(f"Passed: {description}", flush=True)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out after {timeout}s: {description}")
        print(f"Waiting: {description}", flush=True)
        time.sleep(10)


def wait_for_function(function_name, *, binding_type=None, schedule=None, timeout=300):
    """Wait for a running host and named function; return hostname and secret key.

    Optional binding_type and schedule restrict the expected trigger. The caller
    must not log the returned key. This checks readiness without invoking the app.
    """
    require(bool(function_name), "Expected a function name")
    require(schedule is None or binding_type is not None, "A schedule requires a binding type")
    hostname = required_field(az("show"), "defaultHostName", "show")
    key = None

    def ready():
        nonlocal key
        try:
            key = az("keys", "list").get("masterKey")
            if not key:
                return False
            _, status = host_request(hostname, key, "/admin/host/status")
            if status.get("state", "").lower() != "running":
                return False
            functions = az("function", "list")
            return any(
                f["name"].split("/")[-1] == function_name
                and (binding_type is None or any(
                    b.get("type", "").lower() == binding_type.lower()
                    and (schedule is None or b.get("schedule") == schedule)
                    for b in f.get("config", {}).get("bindings", [])))
                for f in functions
            )
        except (RuntimeError, HTTPError, URLError, TimeoutError, subprocess.TimeoutExpired):
            return False

    wait_until(ready, "host running and expected function indexed", timeout=timeout)
    return hostname, key
