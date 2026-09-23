# Use templates from an application repository

[Repository README](../../../README.md)

New downstream repositories should register separate CI and CD pipelines using
[ci.yml](../../../examples/azure-functions/python/ci.yml) and
[cd.yml](../../../examples/azure-functions/python/cd.yml). Copy these into the application's
`.azure-pipelines/` folder. CI tests and publishes the app; CD deploys the selected
successful CI run without rebuilding it. Both definitions belong in the same
application repository and Azure DevOps project.

Register the downstream pipelines as follows:

1. Publish the platform template changes to Azure Repos first. Commit the example
   CI/CD files to the app repository and use the same tested platform release tag
   in both repository resources. The examples follow `main` only to remain usable
   before the first release tag exists.
2. Register `.azure-pipelines/ci.yml` as `<app>-ci` using **Existing Azure Pipelines
   YAML file**. Run it and add it to the app's required PR build-validation policy.
   CI needs an agent and dependency access, but no Azure target or credentials.
3. When Azure infrastructure is ready, replace the placeholders in `cd.yml`:
   the CI pipeline name, Azure service connection, Function App and environment.
   Register `.azure-pipelines/cd.yml` as `<app>-cd` and authorize its resources.
4. The CD example has no push trigger. A successful CI completion on
   `refs/heads/main` starts CD. There is no stage filter: all CI stages must finish
   successfully, including any additional integration tests the app adds. Configure
   environment approvals and an exclusive lock as appropriate for the target.

CD uses a pipeline resource alias (`appCI`) and `artifactPipeline: appCI` to fetch
that exact run's `function-package/function-app.zip`. It checks the run through the
Azure DevOps API using `System.AccessToken`; the CD Build Service identity needs
permission to view the CI builds and download their artifacts. This token is
provided by Azure DevOps, not a separately configured PAT. API failure blocks
deployment. CI and CD must use the same project and app repository in this version.

Same-repository completion triggers select the CI commit for CD, keeping checked-out
deployment hooks aligned with the package. Manual CD runs also verify the selected
CI commit matches the CD checkout; selecting an older artifact while checking out
newer `main` will fail. Use the completion-triggered run (or a matching-commit CD
run) rather than mixing revisions. Pin both platform refs to the same release tag
to keep shared templates and shared Python consistent across the two runs.
See [Microsoft's pipeline resource documentation](https://learn.microsoft.com/en-us/azure/devops/pipelines/yaml-schema/resources-pipelines-pipeline?view=azure-pipelines).

For a combined pipeline, use
[the combined starter](../../../examples/azure-functions/python/azure-pipelines.yml),
which extends `templates/azure-functions/python/ci-cd.yml`. The
[composition example](../../../examples/azure-functions/python/ci-cd.yml) also shows the two
components in a single run when needed.

For platform references in the same project use `type: git`, `name: platform-dev`
and the `platform` resource alias. No extra repository service connection is needed.

The pipeline Build Service identity needs Read permission on `platform-dev`.
Authorize the repository resource, Azure service connection and deployment
environment for each consuming pipeline. For Azure Repos PR checks, configure
a build-validation branch policy on the app's `main` branch.

The resource currently follows `refs/heads/main`. Merge the shared template before
the consumer changes. Azure DevOps compiles templates from remote Git, so local
sibling folders alone are insufficient. By default only `self` is checked out.
Set `usePlatformPython: true` to also check out the platform repository in Build
and Deploy. Both YAML and Python then come from the same resolved resource ref.
App-specific hook templates must use an absolute repo path with `@self`.

Before enabling CD for a new app, provision its Function App and required Azure resources,
configure its runtime and app settings, and grant deployment permissions. Choose
an environment appropriate to that target and configure an exclusive lock check
if deployments need serialization. Run CI first and review the test results and
artifact before registering CD. For a combined pipeline, start with `deploy: false`.

See also the [template reference](template-reference.md), [shared Python helpers](shared-python.md),
and [release and rollout guidance](releasing.md).
