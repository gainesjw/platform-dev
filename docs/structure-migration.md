# Workload-first structure migration

The registered **platform-dev-validation** pipeline keeps its existing YAML path:
`.azure-pipelines/azure-pipelines.yml`. That file retains triggers and agent selection,
and references private workload validation files
under `.azure-pipelines/validation/`. No pipeline path change is required.

Templates, examples, docs and tests are organized by workload. CI and CD are
children of the workload's template folder. The standardized entry points are:

| Previous path/import | Standardized path/import |
| --- | --- |
| `templates/ci/azure-functions/python/stages.yml` | `templates/azure-functions/python/ci/stages.yml` |
| `templates/cd/azure-functions/python/stages.yml` | `templates/azure-functions/python/cd/stages.yml` |
| `templates/azure-functions/python/stages.yml` | `templates/azure-functions/python/ci-cd.yml` |
| `templates/ci/fabric/stages.yml` | `templates/fabric/ci/stages.yml` |
| `templates/cd/fabric/stages.yml` | `templates/fabric/cd/stages.yml` |
| `platform_deployment.azure_functions` | `platform_azure_functions.deployment` |
| `examples/azure-functions-python/` | `examples/azure-functions/python/` |
| Root Functions tests and fixtures | `tests/azure_functions/python/` |
| Platform root `requirements-dev.txt` | `requirements/azure-functions/python/test.txt` |
| `tests/requirements.txt` | `requirements/shared/test.txt` |
| `python/platform_fabric/requirements.txt` | `requirements/fabric/runtime.txt` |

Fabric validation installs `requirements/fabric/test.txt`. The Function App fixture
runtime pins live in `requirements/azure-functions/python/smoke-runtime.txt` and
are copied into its temporary package as `requirements.txt`. Consumer application
requirements files and reusable template defaults are unchanged.

Internal templates remain next to their family's public entry points. The old
phase-first template paths and old Python package are not compatibility aliases.
Existing immutable release tags still contain their original paths.

## Updated consumers

- `data-acquisition`: CI/CD references, validation helper imports, contract tests
  and deployment documentation point to the new Functions paths/package.
- `analytics-dev` and `data-engineering-dev`: CI/CD references point to the new
  Fabric paths. Their manifest generation and promotion behavior are unchanged.
- Platform validation, starters, catalog and guides reference the new structure.

## Publish without mixing revisions

This is a coordinated consumer migration, not an in-place compatible release.
Do not merge the platform reorganization alone while consumers following main
still use old paths. Publish/test the candidate on a feature branch or release
tag, then update consumer CI/CD repository refs and paths together. Alternatively,
pin existing consumers to a known-good pre-migration release before changing
platform main. Keep the Functions helper checkout on the same platform revision
as its templates. No release tag has been created by this local change.

Run platform validation at the candidate revision before rollout. Local tests
validate references and selected scripts; Azure DevOps must still compile and
run the templates remotely. Fabric workspace IDs, service connections and
environment approvals remain separate activation requirements.
