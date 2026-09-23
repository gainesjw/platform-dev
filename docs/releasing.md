# Release and rollout

For the current workload-first reorganization, follow
[the coordinated structure migration](structure-migration.md) before the general
release procedure below. Public template paths and the Functions helper import changed.

1. Run shared contracts and the relevant workload's tests in its documented
   runtime. Run platform validation in Azure DevOps to check candidate template
   expansion and artifact behavior.
2. Keep public entry points, parameters, imports and artifact contracts compatible.
   Introduce a new versioned path for a breaking change, with migration guidance.
3. Publish `platform-dev` before consumer changes. Create an immutable tested
   release tag and update a consumer's CI and CD refs together through review.
4. Validate a representative consumer in its dev/sandbox target before production.
   Retain artifacts and deployment receipts for the required audit/rollback window.

The platform repository does not deploy consumer applications or workspaces by
itself. Following main adopts changes on the consumer's next run; it does not
automatically queue that consumer. Initial starters follow main until a release
tag exists. Do not reference a nonexistent tag.

Workload rollout and recovery details:

- [Azure Functions/data-acquisition migration](azure-functions/python/releasing.md)
- [Fabric analytics/data-engineering activation](fabric/README.md)

Remote pipeline registration, service connections, workspace provisioning and
approvals must be completed in Azure DevOps/Fabric. Local passing tests do not
establish that those resources or permissions exist.
