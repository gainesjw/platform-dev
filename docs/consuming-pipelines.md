# Consume platform CI/CD templates

Start with the workload entry in [the catalog](../catalog.json).

| Workload | Starter | Setup guide |
| --- | --- | --- |
| Python Azure Functions | [examples](../examples/azure-functions/python/) | [Functions setup](azure-functions/python/consuming-pipelines.md) |
| Fabric workspace items | [examples](../examples/fabric/) | [Fabric setup](fabric/README.md) |

Consumers own triggers, source and target configuration. Platform templates own
reusable CI/CD behavior. Each family has independent artifacts, dependencies and
deployment tasks. Register separate CI/CD pipelines, authorize their repository
and pipeline resources, and keep both platform refs on the same tested release.

Publish the platform changes before consumer YAML. For Azure Repos, configure a
main build-validation branch policy; YAML `pr` is not an Azure Repos branch policy.
Create environment approvals/checks and deployment resource permissions before
enabling CD. Workspace creation, service connections and permissions are external
setup actions, not side effects of copying a starter.

See [repository conventions](repository-layout.md) for adding a new workload family
instead of a new consumer of an existing family.
