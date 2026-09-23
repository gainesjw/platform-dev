# Public template entry points

| Workload | CI | CD | Reference |
| --- | --- | --- | --- |
| Python Azure Functions | `templates/azure-functions/python/ci/stages.yml` | `templates/azure-functions/python/cd/stages.yml` | [parameters](azure-functions/python/template-reference.md) |
| Fabric workspace items | `templates/fabric/ci/stages.yml` | `templates/fabric/cd/stages.yml` | [release/configuration contract](fabric/README.md) |

The optional combined Function App entry point,
`templates/azure-functions/python/ci-cd.yml`, composes the two family components.
New consumers should use separate CI/CD entry points. Adjacent step/environment
templates are internal implementation components; consumers should target the
public `stages.yml` entry points.

The [catalog](../catalog.json) also records runtimes, artifacts, examples, tests
and helper packages. Follow the [placement conventions](repository-layout.md)
when extending the platform.

Older phase-first template paths were moved during standardization. See
[the migration map](structure-migration.md) when upgrading an existing consumer.
