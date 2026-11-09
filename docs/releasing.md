# Publishing releases

This guide is for maintainers publishing `google-ads-mcp` to TestPyPI, PyPI,
GitHub Releases, and GHCR. The release workflow uses PyPI Trusted Publishing and
short-lived OpenID Connect (OIDC) credentials. Do not create a `PYPI_TOKEN` or
store a PyPI password in GitHub.

The workflow file name and GitHub environment names are part of the trusted
identity. If any of them changes, update the publisher configuration on the
corresponding package index before attempting another publication.

## Required access

The maintainer performing the one-time setup needs:

- repository administration access for `googleads/google-ads-mcp`;
- Owner or Maintainer access to `google-ads-mcp` on PyPI; and
- access to the corresponding project on TestPyPI, or permission to create a
  pending publisher there.

## Configure GitHub environments

In the repository, open **Settings > Environments** and create these two
environments:

- `pypi` for production releases; and
- `testpypi` for manual rehearsals.

For `pypi`, configure at least one required reviewer and restrict deployments
to tags matching `v*`. Do not allow administrators to bypass the production
approval unless the repository's incident procedure explicitly requires it.
Required reviewers are optional for `testpypi`, but the environment must still
exist because its name is included in the OIDC identity.

## Register the PyPI Trusted Publisher

Follow PyPI's guide for [adding a publisher to an existing
project](https://docs.pypi.org/trusted-publishers/adding-a-publisher/):

1. Sign in to PyPI and open **Your projects**.
2. Select **Manage** for `google-ads-mcp`.
3. Open **Publishing**.
4. Add a GitHub Actions publisher with these exact values:

   | Field | Value |
   | --- | --- |
   | Owner | `googleads` |
   | Repository name | `google-ads-mcp` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

After registration, the `publish-pypi` job can request a short-lived token.
The job grants `id-token: write` only for that publication and uses PyPA's
official [Trusted Publishing
action](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Register the TestPyPI Trusted Publisher

Sign in to [TestPyPI](https://test.pypi.org/) and register a separate GitHub
Actions publisher. Use the same values as production except for the environment:

| Field | Value |
| --- | --- |
| Owner | `googleads` |
| Repository name | `google-ads-mcp` |
| Workflow name | `release.yml` |
| Environment name | `testpypi` |

PyPI and TestPyPI are separate services. Registering the production publisher
does not configure TestPyPI.

## Rehearse a release on TestPyPI

The manual workflow is available after `release.yml` has been merged into the
repository's default branch.

1. Open **Actions > Release > Run workflow**.
2. Select the revision to test and start the workflow.
   Leave **Test GHCR in a fork without publishing to TestPyPI** unchecked.
3. Approve the `testpypi` environment if reviewers are configured.
4. Wait for both **Build and validate distributions** and **Publish to
   TestPyPI** to finish.
5. Verify the new release on TestPyPI. Its version is derived from the declared
   version and the unique workflow run ID, for example
   `0.0.1.dev123456789`.
6. Download the Actions artifact and verify that it contains one wheel, one
   source distribution, and `SHA256SUMS`.

The version change exists only in the runner workspace. It is never committed
and the TestPyPI distributions are never reused for production. If a rehearsal
must be repeated after it has published, start a new workflow run instead of
rerunning the completed publication job; the new run receives a new version.

## Publish a production release

### Prepare the version

1. Choose a new, unused `X.Y.Z` version that follows PEP 440.
2. Create a pull request that changes only `project.version` in
   `pyproject.toml`.
3. Run and approve all required CI checks.
4. Merge the version pull request into `main`.
5. Confirm that the version does not already exist on PyPI.

### Create the release tag

From an up-to-date `main`, create and push an annotated tag:

```shell
git switch main
git pull --ff-only
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

Do not create the tag on an unmerged commit. Do not move or reuse it after it
has been pushed.

The workflow rejects a production tag unless all of these conditions hold:

- the tag uses the exact `vX.Y.Z` format;
- it is annotated;
- `X.Y.Z` matches `project.version`;
- the tagged commit belongs to `origin/main`; and
- the version does not already exist on PyPI.

### Approve and verify publication

1. Approve the `pypi` environment deployment.
2. Confirm that **Publish to PyPI** succeeds.
3. Confirm that **Publish container to GHCR** succeeds, then that
   **Create GitHub Release** succeeds afterward.
4. Verify the wheel and source distribution on PyPI.
5. Verify that the GitHub Release contains those same files and
   `SHA256SUMS`, plus the container digest reference. Verify that the version
   image is publicly pullable and its metadata matches the tagged commit.
6. Install the exact published version:

   ```shell
   pipx run --spec "google-ads-mcp==X.Y.Z" google-ads-mcp
   ```

7. Close the release issue only after at least one new production version is
   available and installable.

## Configure GHCR publication

The production chain is package validation, container validation, protected
PyPI publication, GHCR publication, and finally GitHub Release completion.
Container publication failure blocks GitHub Release completion. PyPI and GHCR
cannot be published atomically; use the recovery procedure below after a partial
publication.

The GHCR job uses the repository's short-lived `GITHUB_TOKEN` with job-scoped
`packages: write`. It has no `environment` declaration and needs no GHCR-specific
approval or registry secret. Its dependency on the successful protected `pypi`
job makes the existing PyPI environment the production approval gate. Keep the
existing PyPI/TestPyPI Trusted Publisher configurations.

A repository/organization administrator must complete this setup:

1. Confirm organization policy permits package creation and public packages in
   `googleads`, and permits Actions to grant `packages: write` to this job.
2. Check whether `ghcr.io/googleads/google-ads-mcp` already exists. Verify its
   repository association and grant `googleads/google-ads-mcp` write access under
   **Package settings > Manage Actions access** if it does not inherit access.
3. Arrange for an administrator of the package to make it public after the first
   successful publication: open **Package settings > Change visibility**. New
   GHCR packages default to private, even when the source repository is public.
4. Verify anonymous access with an empty Docker credential configuration:

   ```shell
   task_docker_config="$(mktemp -d)"
   DOCKER_CONFIG="$task_docker_config" docker pull ghcr.io/googleads/google-ads-mcp:X.Y.Z
   rmdir "$task_docker_config"
   ```

No new environment named `ghcr` is required. Organization package policy and
package access remain separate requirements from environment approval.

### Image and tag policy

Images initially support `linux/amd64`. Version `X.Y.Z` contains the tagged
source and OCI source, version, revision, and license labels. The Dockerfile's
existing runtime compatibility patch remains part of the image.

The container is built and smoke-tested without Google credentials or network
access, saved to a checksummed Actions artifact, and retained for seven days.
The publication job loads that archive and never rebuilds it. Dependencies and
base images currently float, so a later rebuild may produce different content.

Publication first pushes a `candidate-<run-id>` tag, establishing registry access
for a new package. It then publishes `X.Y.Z`, refusing to overwrite an existing
version with different image content. An identical version image is accepted
on retry. Candidate tags are operational artifacts, not supported deployment
references; retain them for recovery, and clean up old candidates according to
the organization's package retention policy without deleting release versions.

`latest` points to the highest stable `X.Y.Z` published by this workflow. Older
maintenance releases do not move it backward. GitHub Release's **Latest** flag
uses the same decision. These updates occur before release completion, so a
failed finalization can temporarily leave a container available before its
GitHub Release; rerun the failed jobs to finish the release.

Production workflow runs share one concurrency group to prevent racing tag
updates. Start one production release at a time: GitHub concurrency keeps at
most one pending run and may replace an older pending run. PRs and manual
rehearsals have separate concurrency groups. Do not modify registry tags outside
this workflow. Use the published digest for fixed deployments; GHCR itself does
not enforce tag immutability.

### Rehearse GHCR in a fork

The existing release workflow supports a manual rehearsal independent of both
package indexes and production GitHub Releases:

1. Push the implementation branch to your fork. The default branch must already
   contain the dispatch-enabled `release.yml` workflow.
2. Run **Release** against the implementation branch with
   **Test GHCR in a fork without publishing to TestPyPI** checked. For example:

   ```shell
   gh workflow run release.yml --repo OWNER/FORK --ref feature/issue-118-release-docker-image-to-ghcr -f ghcr-rehearsal=true
   ```

3. Confirm package/container builds succeed, **Rehearse GHCR publication in a
   fork** succeeds, and TestPyPI, production PyPI, production GHCR, and GitHub
   Release jobs are skipped. No environment approval should be requested.
4. Inspect `ghcr.io/owner/fork-ghcr-rehearsal:X.Y.Z`, its `latest` tag and OCI
   labels. `X.Y.Z` is the declared source version, not the TestPyPI development
   version generated in the separate package-build workspace.
5. Make the rehearsal package public if desired and verify anonymous pulling.
   Rerun only the rehearsal publication job to verify identical-image recovery.

The rehearsal input cannot publish in `googleads/google-ads-mcp`; its publication
job is restricted to forks and always uses the separate `-ghcr-rehearsal` package.
Rebuilding the same version in a new run can correctly fail the immutable-tag
check. Use a new source version for another build, or rerun only the publication
job against the original retained archive. A successful fork rehearsal verifies
that fork's permissions, not the upstream organization's package policy.

Future ARM64 support can use QEMU or hosted native ARM64 runners without local
ARM64 hardware. It requires platform tests and a multi-platform publication
design; a single Docker image archive cannot represent a manifest list.

## Failure recovery

- **Failure before PyPI publication:** correct the source through a pull
  request, choose a new version, and create a new tag. Do not move a pushed
  release tag.
- **PyPI succeeded but GHCR failed:** correct permissions or transient registry
  failures and use **Re-run failed jobs** in the original run. The checksummed
  image artifact must still exist. Do not rerun successful package/container
  builds or PyPI publication: package validation rejects versions already on PyPI.
  An already pushed identical version is reused; different image content fails.
- **Image artifact expired:** do not rebuild and overwrite that version. Publish
  a new version/tag, or arrange a separately reviewed recovery using the existing
  registry image when its identity can be established.
- **GHCR push succeeded but anonymous pulling fails:** check package visibility
  and repository/Actions access. A green push job does not prove public access.
- **PyPI and GHCR succeeded but GitHub Release failed:** use **Re-run failed jobs** so
  the release job resumes its draft or verifies the already published assets.
  Do not rerun the successful PyPI job.
- **Defective published version:** yank it on PyPI when appropriate and publish
  a corrected version. PyPI distributions cannot be overwritten.
- **Interrupted TestPyPI rehearsal:** start a new manual run if the package was
  already uploaded, because every uploaded version is immutable.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| Trusted Publisher reports an invalid publisher | Owner, repository, workflow, or environment differs from the registered identity | Compare all four values character for character and update the index configuration if the workflow was renamed. |
| The workflow cannot request an OIDC token | The publication job lacks `id-token: write` or is not using the registered environment | Keep `id-token: write` on the publication job and select the exact `pypi` or `testpypi` environment. |
| Publication waits indefinitely | A protected environment is awaiting review | Ask an allowed reviewer to approve or reject the deployment in GitHub Actions. |
| PyPI says a file or version already exists | The version was already uploaded | Never enable `skip-existing` for production. Choose a new version and tag. |
| Production validation rejects the tag | The tag is lightweight, mismatches `project.version`, or is not on `main` | Merge the version change first, then create a new annotated tag from the merged commit. |
| A TestPyPI rerun reports a duplicate version | The successful dispatch was rerun with the same run ID | Start a new manual workflow run to generate a new `.dev` version. |
