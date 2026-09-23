# Platform validation

Tests are grouped by workload, with common contracts in `tests/contracts/`.
Run the complete offline suite using the existing Python 3.14 convenience environment:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements/azure-functions/python/test.txt
.venv/bin/python -m pytest
```

This includes no Fabric SDK import or live Azure/Fabric calls. The one GNU copy
test is Linux-only. The actual Docker host test is selected explicitly in the
[Functions validation flow](azure-functions/python/testing.md).

Fabric SDK compatibility is validated separately with its supported runtime:

```bash
python3.12 -m venv .venv-fabric
.venv-fabric/bin/python -m pip install -r requirements/fabric/test.txt
.venv-fabric/bin/python -m pytest tests/fabric tests/contracts
PYTHONPATH=python .venv-fabric/bin/python tests/fabric/fabric_sdk_smoke.py
.venv-fabric/bin/python -m pip check
```

The SDK smoke uses a fake credential and target inventory, blocks outbound HTTP,
and exercises the real parameter parser and notebook/SQL/report rebinding code.
It does not require Azure CLI login or workspace access.

`.azure-pipelines/azure-pipelines.yml` preserves the registered platform entry
point. It runs Fabric tests/SDK checks in Python 3.12, Functions tests/contracts
in Python 3.14, and the existing Function App build/artifact/container tests.
Dependencies are installed per job. Tests parse YAML and execute selected scripts;
only an Azure DevOps run verifies server-side template expansion, repository
permissions and deployment environment checks. No live deployment is part of
this offline suite.
