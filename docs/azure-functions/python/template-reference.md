# Python Function App template reference

[Repository README](../../../README.md)

[templates/azure-functions/python/ci-cd.yml](../../../templates/azure-functions/python/ci-cd.yml)
remains an `extends` template with Build and optional Deploy stages, delegating to
the separate CI and CD components. Its parameters and defaults are unchanged:

1. Select Python on a Linux agent, install development dependencies and run
   `pip check`, execute tests and publish JUnit and coverage reports.
2. Install runtime dependencies into `.python_packages/lib/site-packages`, copy
   explicitly selected application files, run optional package validation, verify
   that `function_app.app` imports and indexes at least one function, compile Python
   and publish `function-package/function-app.zip`.
3. If deployment is enabled, deploy the current build's ZIP through
   `AzureFunctionApp@2`, with optional steps before and after deployment. Only
   successful builds of the configured deployment branch may deploy; PRs cannot.

The default app contract is the Python v2 programming model with `function_app.py`
exporting `app`, `host.json`, `requirements.txt`, `requirements-dev.txt`, `src/`,
and `tests/unit/`. Development dependencies must include pytest and pytest-cov.
Imports must work on the build agent without Azure credentials, or package hooks
must provide any required configuration. This template currently targets Python
on Linux; other languages and operating systems need their own templates.

| Parameter | Default / purpose |
| --- | --- |
| `azureServiceConnection` | Required Azure deployment service connection name |
| `functionAppName` | Required existing Function App name |
| `deploy` | `false`; include the deployment stage |
| `pythonVersion` | `'3.14'`; must match the target app runtime |
| `isFlexConsumption` | `true`; set `false` for non-Flex Linux hosting, which uses zipDeploy and runtimeStack |
| `vmImage` | `ubuntu-latest`; use a compatible hosted Linux image |
| `environment` | `production`; Azure DevOps environment |
| `deploymentBranch` | `refs/heads/main`; full Git ref allowed to deploy |
| `runtimeRequirements` | `requirements.txt`; runtime dependency file |
| `devRequirements` | `requirements-dev.txt`; test/development dependency file |
| `testCommand` | pytest on `tests/unit`, covering `src` and `function_app` |
| `packagePaths` | `[src, function_app.py, host.json, requirements.txt]`; literal repo-relative files/directories, preserving structure; no globs |
| `usePlatformPython` | `false`; check out shared Python and expose it to the test command |
| `platformRepository` | `platform`; alias of this repo in the consumer repository resources |
| `appCheckoutPath` | `s` for compatibility; new consumers should use `s/$(Build.Repository.Name)` |
| `platformCheckoutPath` | `platform` for compatibility; new consumers should use `s/platform-dev` |
| `packageValidationSteps` | Empty step list; runs after package files are copied, before generic package validation and archive |
| `beforeDeploySteps` | Empty step list; runs after app checkout, artifact download and Python selection, before deployment |
| `afterDeploySteps` | Empty step list; runs after successful deployment |

The CI component accepts only the build/test, checkout and package-hook parameters
from this table. It does not require `azureServiceConnection` or `functionAppName`.
The CD component accepts deployment, checkout and deploy-hook parameters plus:

| CD-only parameter | Default / purpose |
| --- | --- |
| `artifactPipeline` | `current`; set to the upstream pipeline resource alias, such as `appCI`, for separate CD runs |
| `dependsOn` | `[Build]`; set `[]` for a standalone CD pipeline |

The standalone CD example explicitly sets `deploy: true`; create/enable it only
after configuring the deployment target. The compatibility wrapper retains
`deploy: false` by default. CD never installs application dependencies, executes
app unit tests or builds a replacement ZIP.

Custom `testCommand` values must create `test-results/unit.xml` and `coverage.xml`;
missing reports fail the build. Package paths are an explicit allowlist: include
all app resources, omit local settings and secrets, and do not include the repo
root or local virtual environments. If you change the runtime requirements path,
update `packagePaths` as needed. Package hooks can access the staging folder at
`$(Build.ArtifactStagingDirectory)/function-package`. Deployment hooks can access
the ZIP through `$(functionPackagePath)`. This resolves to
`$(Pipeline.Workspace)/function-package/function-app.zip` for a combined run and
`$(Pipeline.Workspace)/<pipeline-alias>/function-package/function-app.zip` for a
separate CD run. Update hooks with hard-coded ZIP paths when migrating to separate
pipelines; the old combined-run path remains unchanged.
Hooks can also use `$(artifactBuildId)` and `$(artifactSourceVersion)` to validate
the identity embedded in the package. These identify the selected CI run for
separate CD pipelines and the current build for combined pipelines. Do not use
the CD run's `$(Build.BuildId)` to verify a manifest stamped during CI.

Hooks run against the checked-out app repo and are responsible for their own
dependencies, AzureCLI service connection and environment variables. The shared
template does not assume a collector, storage account, timer name or output format.
It does not provision infrastructure, configure application-specific settings or
provide a default post-deployment health check. Add those checks in app hooks.
Deployment failures do not automatically roll back an already deployed app.

See also [consumer setup](consuming-pipelines.md) and [shared Python helpers](shared-python.md).
