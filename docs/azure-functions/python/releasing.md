# Release and consumer rollout

[Repository README](../../../README.md)

`data-acquisition` keeps its production variables, deployment validation Python
script and three app-specific YAML hooks. Its script imports the shared
`platform_azure_functions.deployment` module for runtime and readiness checks. Those hooks preserve its build manifest,
collector indexing assertion, destination configuration, Azure preflight checks,
and timer invocation/blob verification.

Merge/push `platform-dev` first, then the `data-acquisition` consumer change.
`usePlatformPython` defaults to false so existing consumers continue to work while
this release is rolled out. The updated data-acquisition consumer opts in.
The migrated consumer uses `.azure-pipelines/ci.yml` for CI and
`.azure-pipelines/cd.yml` for CD. Update its existing CI definition to the new YAML
path. Rename its existing
`data-acquisition-ci-cd` definition to `data-acquisition-ci` and register
`data-acquisition-cd` after CI passes. For a build-only first run, use a feature
branch; once CD is registered, successful main CI runs trigger production CD.
The collector's output verification uses the upstream CI build ID and commit.
Local YAML parsing cannot validate Azure DevOps permissions or server-side template
expansion; a remote run is required for those checks.

Following `main` shares updates on the next consumer run; editing this repo does
not itself queue app pipelines. For controlled upgrades, create release tags in
this repo and pin consumers to an existing `refs/tags/<version>` resource `ref`.
Test changes against a consumer before releasing and retain compatibility for
existing parameters or publish a new template path for breaking changes.

Reference: [Microsoft's cross-repository YAML template documentation](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/templates?view=azure-devops#store-templates-in-other-repositories).

See also [consumer setup](consuming-pipelines.md) and [validation coverage](testing.md).
