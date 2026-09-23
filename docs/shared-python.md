# Python deployment packages

| Package | Responsibility | Runtime dependencies |
| --- | --- | --- |
| `python/platform_azure_functions` | Existing Azure Functions validation helpers | [Functions API](azure-functions/python/shared-python.md); standard library helpers |
| `python/platform_fabric` | Fabric inventory, artifact verification and promotion | [Pinned Fabric requirements](../requirements/fabric/runtime.txt), Python 3.12 |

These packages do not import one another. Functions helpers are imported from
`platform_azure_functions.deployment`. New workload packages use
`platform_<workload>` and own their dependencies. `requirements/shared/test.txt` contains
test tools and must not be used as a deployment requirements file.

Fabric copies its tooling and requirements into the CI artifact so promotions do
not load newer Python code from main. Functions consumers retain their existing
explicit platform checkout and `PYTHONPATH` behavior. See the workload guides for
details rather than treating the two artifact contracts as interchangeable.

The former `platform_deployment.azure_functions` import moved to
`platform_azure_functions.deployment`; update the consumer import and platform
revision together. See [migration instructions](structure-migration.md).
