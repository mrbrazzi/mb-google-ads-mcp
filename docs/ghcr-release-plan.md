# Issue #118: GHCR release design

Branch: `feature/issue-118-release-docker-image-to-ghcr`.

## Agreed requirements

- Start with `linux/amd64`; defer ARM64. QEMU or hosted ARM64 runners can provide
  future validation without local ARM64 hardware.
- Publish the exact release version and a `latest` alias.
- Block GitHub Release completion until the container is published.
- Reuse the existing PyPI approval; do not add a GHCR environment.
- Provide a fork rehearsal to verify GHCR publication without package-index
  publication. Document additional maintainer setup in the upstream PR.
- Write all code and documentation in English.

## Implementation

```text
Production tag vX.Y.Z:
  validate package/tag -> build/test image -> protected PyPI publication
    -> publish GHCR version/latest -> complete GitHub Release with digest

Pull request:
  validate package -> build/test image; no publication

Default manual dispatch:
  validate development package -> TestPyPI
  validate source-version container; no GHCR publication

Manual fork dispatch with ghcr-rehearsal=true:
  validate package -> build/test source-version image
    -> publish owner/fork-ghcr-rehearsal; no PyPI or GitHub Release
```

The production image name is derived from the repository, producing
`ghcr.io/googleads/google-ads-mcp:X.Y.Z` upstream. No fork can publish to the
upstream namespace through this workflow. The rehearsal uses a separate package.

The existing Dockerfile is retained. An allowlist in `.dockerignore` restricts
the build context to application/package inputs. The smoke test initializes
the real MCP entry point and lists tools without network access or credentials.
The tested image is transferred as a checksummed archive, never rebuilt during
publication, and retained for seven days.

A run-specific candidate push establishes GHCR package access. Registry queries
then distinguish a missing manifest from permission/network failures. Existing
release tags are reused only when image identity matches the tested archive.
`latest` advances with stable numeric versions; older maintenance releases do
not move it backward. GitHub's Latest flag uses the same decision. Production
concurrency serializes release runs. Registry publication and GitHub Release
completion are separate operations, so failure recovery remains necessary.

`publish-ghcr` has job-scoped `packages: write`, uses `GITHUB_TOKEN`, and depends
on successful protected PyPI publication. No `ghcr` environment is declared.
The fork rehearsal grants the same package permission without an environment.

## Maintainer setup and PR requirements

The upstream PR must explicitly call out:

1. Organization permission to create/publicize GHCR packages and grant Actions
   package write access.
2. Existing package ownership, repository linkage, and **Manage Actions access**.
3. The first-publication step: a package administrator changes visibility from
   private to public and verifies an anonymous pull.
4. The unchanged PyPI environment approval gate and Trusted Publisher identity.
5. Version/latest policy, `linux/amd64` support, candidate retention, the seven-day
   artifact recovery window, and rerunning only failed publication jobs.
6. Fork rehearsal evidence and any upstream-only acceptance checks still pending.

The operational procedure is in [the release guide](releasing.md). Fork settings
cannot establish that the upstream organization permits package publication.

## Validation record

- Local isolated Podman image build: passed with the existing Dockerfile.
- Network-isolated MCP initialization and tools listing: passed, version 0.0.6.
- Thirteen publication tests pass, covering immutable versions, retries,
  latest/backfills, metadata mismatch, registry errors, OCI indexes, and config
  identity in both classic and containerd image archives.
- `actionlint` (including ShellCheck), Black formatting, and offline `zizmor`
  checks pass. Zizmor reports no findings with its default suppressions.
- [Fork rehearsal on implementation commit 669868b](https://github.com/mrbrazzi/mb-google-ads-mcp/actions/runs/42722978995)
  passed package validation, image validation, and GHCR publication. TestPyPI,
  production PyPI/GHCR, and GitHub Release jobs were skipped. The fork has zero
  configured environments; the publication job received `packages: write` and
  completed without environment approval.
- The rehearsal published `0.0.6` and `latest` in the isolated package
  `ghcr.io/mrbrazzi/mb-google-ads-mcp-ghcr-rehearsal`, with manifest digest
  `sha256:07291d8ec03259426e95e2ee0f0791b01c2ffc908f424c2e7474704eaa5dd273`.
- [Publication-only retry, attempt 2](https://github.com/mrbrazzi/mb-google-ads-mcp/actions/runs/42722978995/attempts/2)
  succeeded against the retained artifact and identical manifest digest. The
  existing version was reused without rebuilding or republishing Python packages.
- The initial integration runs exposed Docker/containerd image identity
  differences. The fix was verified against an actual downloaded runner archive:
  its config digest matches the build log. The script reads config identity from
  the archive instead of assuming `docker inspect .Id` is always a config digest.

Upstream organization permissions, the protected production approval path, and
anonymous pulling after the one-time visibility change require a maintainer's
real production release. The fork rehearsal does not establish these upstream
conditions and does not publish to either package index.

## Suggested upstream PR description

Publish Docker images to GHCR during the existing annotated-tag release process.
Validate the image before PyPI publication, reuse the tested image archive, and
require successful GHCR publication before completing the GitHub Release. Publish
version and latest tags for linux/amd64 and include the registry digest in release
notes. PR builds and ordinary TestPyPI rehearsals never publish containers.

Maintainers must confirm organization/package write access and make the package
public after its first publication. No GHCR environment or new registry secret
is needed; the existing PyPI approval gates production publication. The release
guide covers setup, anonymous pull verification, fork rehearsals, and recovery.

Validation: thirteen policy/registry/archive tests, local isolated image build
and MCP smoke test, actionlint, offline zizmor, and the linked fork rehearsal
  passed, including an identical-image publication retry. Production publishers
  and release creation were skipped in the fork
rehearsal. Upstream organization access, protected approval, and public pulling
remain production acceptance checks. Refs #118; close after the first public
production image has been verified.

## References

- [Issue #118](https://github.com/googleads/google-ads-mcp/issues/118)
- [GitHub container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub environment approval rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [Docker multi-platform builds](https://docs.docker.com/build/building/multi-platform/)
- [Moby containerd image inspection implementation](https://github.com/moby/moby/blob/master/daemon/containerd/image_inspect.go)
