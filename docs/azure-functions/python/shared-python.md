# Shared Python deployment utilities

[Repository README](../../../README.md)

[python/platform_azure_functions/deployment.py](../../../python/platform_azure_functions/deployment.py)
provides pipeline-only helpers with no third-party Python dependencies. Execution
requires Python and an authenticated Azure CLI. They are not installed in the
Function App deployment package. Collector Blob SDK dependencies remain in the
app's requirements file.

- `preflight(require_managed_identity=False, require_host_storage=False)` checks
  Linux hosting, running state, Python runtime and legacy runtime settings where
  appropriate, then returns app settings. It reads `FUNCTION_APP_NAME`,
  `RESOURCE_GROUP_NAME`, `PYTHON_VERSION` and `IS_FLEX_CONSUMPTION` (default false).
  Data-acquisition explicitly requires identity and host storage; other apps choose
  their own requirements. Returned app settings may contain secrets; never log them.
- `wait_for_function(name, binding_type=None, schedule=None, timeout=300)` polls
  host readiness and function indexing, optionally matching trigger type/schedule.
  It requires the app name and resource group and returns `(hostname, master_key)`.
  Keep the key private. It does not invoke the function or prove business output.
- `host_request`, `wait_until`, `az`, `require`, and `required_env` support
  application-specific validation. Admin requests reject redirects to avoid
  forwarding the host key; CLI logs omit setting values and raw responses.

To use the module from app hooks, set `usePlatformPython: true` on the shared
template and add this environment entry to each Python/AzureCLI step that imports it:

```yaml
env:
  PYTHONPATH: $(platformPythonPath)
```

Then import it in the app's verification script:

```python
from platform_azure_functions import deployment

settings = deployment.preflight(require_managed_identity=True)
```

Set `appCheckoutPath` and `platformCheckoutPath` to separate sibling directories
under `s`; the starter uses `s/$(Build.Repository.Name)` and `s/platform-dev`.
Data-acquisition explicitly selects `s/data-acquisition` and `s/platform-dev`,
matching Azure's default multi-repo paths and avoiding checkout relocation.
Paths are relative to `$(Pipeline.Workspace)` and must not overlap or contain each
other. `workspaceRepo: true` on the app checkout keeps relative commands and hooks
running from the app root. Test-result and coverage paths explicitly target that
same folder. The job variable `platformPythonPath` follows `platformCheckoutPath`.
The existing defaults (`s` and `platform`) are retained for compatibility during
rollout; update consumers to the sibling layout after publishing this template.
Publish platform-dev first, then the consumer's path parameters and hook changes.
Platform files remain outside the app's package allowlist. The
shared template sets `PYTHONPATH` for the test command when enabled; hooks set it
explicitly. Enabling checkout does not automatically run Azure checks.

For local app tests, clone the matching platform revision and set `PYTHONPATH` to
its `python` folder. Do not add the module to the app's runtime requirements.

See also the [template reference](template-reference.md) for checkout and hook parameters.
