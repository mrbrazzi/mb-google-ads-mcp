"""Publish a tested single-platform image and protect version/latest tags.

The candidate push establishes package access before querying manifests, so an
absent package is never confused with denied access. Registry failures other
than an explicit MANIFEST_UNKNOWN response stop publication.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

MEDIA_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
OCI_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
INDEX_MEDIA_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)


def version_tuple(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError(f"Invalid stable version: {version!r}")
    return tuple(int(part) for part in version.split("."))


class Registry:
    def __init__(self, image, username, password):
        if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", image):
            raise ValueError("Expected a lowercase ghcr.io/owner/image name")
        self.image = image
        self.path = image.removeprefix("ghcr.io/")
        query = urllib.parse.urlencode(
            {"service": "ghcr.io", "scope": f"repository:{self.path}:pull,push"}
        )
        basic = base64.b64encode(f"{username}:{password}".encode()).decode()
        request = urllib.request.Request(
            f"https://ghcr.io/token?{query}",
            headers={"Authorization": f"Basic {basic}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            self.token = json.load(response)["token"]

    def request(self, resource, *, data=None, media_type=None):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": ", ".join(
                (MEDIA_TYPE, OCI_MEDIA_TYPE, *INDEX_MEDIA_TYPES)
            ),
        }
        if media_type:
            headers["Content-Type"] = media_type
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{self.path}/{resource}",
            headers=headers,
            data=data,
            method="PUT" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # A 404 alone is insufficient: distinguish unknown manifests from
            # unknown repositories and permission failures.
            if error.code == 404 and data is None:
                body = json.loads(error.read())
                codes = {item["code"] for item in body.get("errors", [])}
                if codes == {"MANIFEST_UNKNOWN"}:
                    return None
            raise

    def manifest(self, tag):
        raw = self.request(f"manifests/{tag}")
        if raw is None:
            return None
        parsed = json.loads(raw)
        if parsed["mediaType"] in INDEX_MEDIA_TYPES:
            matches = [
                item
                for item in parsed["manifests"]
                if item.get("platform", {}).get("os") == "linux"
                and item.get("platform", {}).get("architecture") == "amd64"
            ]
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one linux/amd64 manifest")
            raw = self.request(f"manifests/{matches[0]['digest']}")
            if raw is None:
                raise RuntimeError("Image index refers to a missing manifest")
            parsed = json.loads(raw)
        if parsed["mediaType"] not in (MEDIA_TYPE, OCI_MEDIA_TYPE):
            raise RuntimeError("Expected a single-platform image manifest")
        return raw, parsed

    def tag(self, tag, manifest):
        raw, parsed = manifest
        self.request(
            f"manifests/{tag}", data=raw, media_type=parsed["mediaType"]
        )

    def labels(self, manifest):
        digest = manifest[1]["config"]["digest"]
        raw = self.request(f"blobs/{digest}")
        return json.loads(raw)["config"]["Labels"]


def publish(registry, version, candidate, expected_id, revision):
    """Keep published versions immutable and latest monotonically increasing."""
    version_tuple(version)
    manifest = registry.manifest(candidate)
    if manifest is None or manifest[1]["config"]["digest"] != expected_id:
        raise RuntimeError("Candidate does not match the tested image")
    labels = registry.labels(manifest)
    if (
        labels.get("org.opencontainers.image.version") != version
        or labels.get("org.opencontainers.image.revision") != revision
    ):
        raise RuntimeError("Candidate version/revision metadata mismatch")

    existing = registry.manifest(version)
    if existing is not None:
        if existing[1]["config"]["digest"] != expected_id:
            raise RuntimeError("Refusing to replace an existing version image")
        manifest = existing
    else:
        registry.tag(version, manifest)

    digest = "sha256:" + hashlib.sha256(manifest[0]).hexdigest()
    if registry.manifest(version)[0] != manifest[0]:
        raise RuntimeError("Published version manifest verification failed")

    latest = registry.manifest("latest")
    promote = latest is None
    if latest is not None:
        previous = registry.labels(latest)["org.opencontainers.image.version"]
        promote = version_tuple(version) >= version_tuple(previous)
    if promote:
        registry.tag("latest", manifest)
        if registry.manifest("latest")[0] != manifest[0]:
            raise RuntimeError("Latest manifest verification failed")
    return digest, promote


def main():
    image = os.environ["IMAGE_NAME"]
    version = os.environ["PACKAGE_VERSION"]
    version_tuple(version)
    run_id = os.environ["GITHUB_RUN_ID"]
    if not run_id.isdigit():
        raise ValueError("Invalid GitHub run ID")
    candidate = f"candidate-{run_id}"
    username = os.environ["GITHUB_ACTOR"]
    password = os.environ["GHCR_TOKEN"]
    local = "release-container:validated"
    expected_id = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", local],
        text=True,
    ).strip()
    subprocess.run(
        ["docker", "login", "ghcr.io", "-u", username, "--password-stdin"],
        input=password,
        text=True,
        check=True,
    )
    try:
        subprocess.run(
            ["docker", "tag", local, f"{image}:{candidate}"], check=True
        )
        subprocess.run(["docker", "push", f"{image}:{candidate}"], check=True)
        registry = Registry(image, username, password)
        digest, promote = publish(
            registry,
            version,
            candidate,
            expected_id,
            os.environ["EXPECTED_REVISION"],
        )
        reference = f"{image}@{digest}"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
            print(f"reference={reference}", file=file)
            print(f"latest={str(promote).lower()}", file=file)
        with open(
            os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8"
        ) as file:
            print(f"Container: `{image}:{version}`\n\n`{reference}`", file=file)
            print(f"\nUpdated latest: {promote}", file=file)
    finally:
        subprocess.run(["docker", "logout", "ghcr.io"], check=True)


if __name__ == "__main__":
    main()
