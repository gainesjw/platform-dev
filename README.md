# Shared Azure and Fabric delivery platform

Reusable Azure Pipelines templates and Python tooling for immutable releases, dependency validation, and selective Fabric deployment.

This portfolio copy demonstrates architecture and implementation using sanitized
configuration. Infrastructure names and Fabric identities are illustrative.
Source Git history, credentials, local settings and data extracts are not included.
Azure Pipelines YAML is provided as a reference; it needs your own Azure DevOps
project, repository resources, targets and service connections to run.

## Portfolio projects

- [data-acquisition](https://github.com/gainesjw/data-acquisition): A Python collector with managed identity, tested storage writes, and verified Azure Functions releases.
- [platform-dev](https://github.com/gainesjw/platform-dev): Reusable Azure Pipelines templates and Python tooling for immutable releases, dependency validation, and selective Fabric deployment.
- [analytics-dev](https://github.com/gainesjw/analytics-dev): A source-controlled Power BI semantic model and report with environment-aware lakehouse bindings.
- [data-engineering-dev](https://github.com/gainesjw/data-engineering-dev): PySpark notebooks that ingest public California healthcare workforce datasets into a Fabric lakehouse.
- [policy-engine-dev](https://github.com/gainesjw/policy-engine-dev): An ASP.NET Core API returning complete artifact manifests and per-item governance findings for pipeline enforcement.

## Implementation guide

# Platform pipelines

Reusable Azure DevOps YAML templates for application repositories in
`example-fabric-project`. Separate template families build and deploy Linux Python
Azure Functions apps and Microsoft Fabric workspace items. Consumer repositories own their code, triggers, target
values and application-specific validation; this repository owns shared CI/CD behavior.

Start with the [template catalog](catalog.json) and
[repository layout/contribution guide](docs/repository-layout.md). Templates are
grouped by workload, then CI/CD phase; examples, guides and tests mirror those
workloads. See the [structure migration](docs/structure-migration.md) for updated
consumer paths and imports.

## Get started with Fabric

Use the Fabric-only CI/CD entry points in `analytics-dev` and
`data-engineering-dev`. Their `.fabric/config.json` files define managed items,
governance and workspace targets. See [Fabric workspace CI/CD](docs/fabric/README.md)
for generated manifests, dependency graphs and dev → test → prod promotion.
For a new project, copy the [Fabric starter](examples/fabric/README.md).

## Get started with Azure Functions

1. Copy [ci.yml](examples/azure-functions/python/ci.yml) into the application's
   `.azure-pipelines/` directory and register it as the app's CI pipeline.
2. When the Azure target is ready, copy [cd.yml](examples/azure-functions/python/cd.yml),
   replace its CI pipeline name and deployment placeholders, and register it separately.
3. Keep both definitions in the same application repository and project. Use the
   same tested platform release tag in both repository resources when available.

CI tests and publishes the app without Azure deployment credentials. CD deploys
the exact successful CI artifact without rebuilding it. See
[consumer setup](docs/azure-functions/python/consuming-pipelines.md) for registration, authorization,
trigger behavior and manual-run requirements.

## Entry points

| Component | Purpose |
| --- | --- |
| [templates/fabric/ci/stages.yml](templates/fabric/ci/stages.yml) | Fabric item validation, generated manifest/graph and immutable release |
| [templates/fabric/cd/stages.yml](templates/fabric/cd/stages.yml) | Fabric dev → test → prod promotion and deployment receipts |
| [python/platform_fabric/](python/platform_fabric) | Independent Fabric governance and deployment tooling, Python 3.12 |
| [templates/azure-functions/python/ci/stages.yml](templates/azure-functions/python/ci/stages.yml) | Reusable build, test and package stage |
| [templates/azure-functions/python/cd/stages.yml](templates/azure-functions/python/cd/stages.yml) | Reusable artifact verification and deployment stage |
| [templates/azure-functions/python/ci-cd.yml](templates/azure-functions/python/ci-cd.yml) | Optional combined CI/CD entry point |
| [.azure-pipelines/azure-pipelines.yml](.azure-pipelines/azure-pipelines.yml) | Platform validation, including package and Docker smoke tests; no deployment |
| [python/platform_azure_functions/](python/platform_azure_functions) | Azure Functions deployment helpers |
| [examples/azure-functions/python/](examples/azure-functions/python) | Separate and combined consumer pipeline examples |

`.azure-pipelines/azure-pipelines.yml` remains the entry point for
**platform-dev-validation**. It composes private workload validation templates
from `.azure-pipelines/validation/`; the pipeline definition does not need a path change.

## Local setup and tests

```bash
cd platform-dev
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements/azure-functions/python/test.txt
.venv/bin/python -m pytest
```

The default local suite needs no Azure resources or credentials. Dependency
installation needs package-index access. Docker testing runs explicitly in the
validation pipeline; see [platform validation](docs/testing.md) for both runtime
environments, local reproduction, prerequisites and coverage limits.

## Documentation

- [Fabric workspace CI/CD](docs/fabric/README.md): analytics and engineering setup,
  generated inventory, governance, environment bindings and promotion checks.
- [Consumer setup](docs/consuming-pipelines.md): workload selection, pipeline registration, resource
  permissions, completion triggers and artifact selection.
- [Template reference](docs/template-reference.md): public entry points, parameters, package contract,
  hooks and artifact variables.
- [Shared Python helpers](docs/shared-python.md): independent packages, imports and checkout paths.
- [Platform validation](docs/testing.md): local tests, CI stages,
  container diagnostics and future sandbox coverage.
- [Release and rollout](docs/releasing.md): publishing order, compatibility,
  release tags and consumer migrations.
- [Repository layout](docs/repository-layout.md): standard locations and adding future workload families.
- [Dependency files](requirements/README.md): shared test tools, workload runtimes and artifact packaging.
