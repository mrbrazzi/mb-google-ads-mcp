"""Exercise publication invariants without registry access or credentials."""

import copy
import hashlib
import json
import unittest
import urllib.error
from io import BytesIO
from unittest import mock

from scripts.publish_container import Registry, publish, version_tuple


def manifest(image_id):
    parsed = {
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"digest": image_id},
    }
    return json.dumps(parsed).encode(), parsed


class FakeRegistry:
    def __init__(self, latest=None, existing=None):
        self.manifests = {"candidate-123": manifest("sha256:tested")}
        self.metadata = {
            "sha256:tested": {
                "org.opencontainers.image.version": "1.2.3",
                "org.opencontainers.image.revision": "source-commit",
            }
        }
        self.writes = []
        if latest:
            self.manifests["latest"] = manifest("sha256:previous")
            self.metadata["sha256:previous"] = {
                "org.opencontainers.image.version": latest
            }
        if existing:
            self.manifests["1.2.3"] = manifest(existing)

    def manifest(self, tag):
        return copy.deepcopy(self.manifests.get(tag))

    def labels(self, value):
        return self.metadata[value[1]["config"]["digest"]]

    def tag(self, tag, value):
        self.writes.append(tag)
        self.manifests[tag] = value


class PublicationTest(unittest.TestCase):
    def publish(self, registry):
        return publish(
            registry, "1.2.3", "candidate-123", "sha256:tested", "source-commit"
        )

    def test_first_release_and_digest(self):
        registry = FakeRegistry()
        digest, latest = self.publish(registry)
        self.assertTrue(latest)
        self.assertEqual(registry.writes, ["1.2.3", "latest"])
        self.assertEqual(
            digest,
            "sha256:"
            + hashlib.sha256(manifest("sha256:tested")[0]).hexdigest(),
        )

    def test_identical_retry_recovers_after_partial_push(self):
        registry = FakeRegistry(existing="sha256:tested")
        self.publish(registry)
        self.assertEqual(registry.writes, ["latest"])

    def test_different_existing_version_is_never_overwritten(self):
        registry = FakeRegistry(existing="sha256:different")
        with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
            self.publish(registry)
        self.assertEqual(registry.writes, [])

    def test_backfill_does_not_downgrade_latest(self):
        registry = FakeRegistry(latest="1.10.0")
        _, latest = self.publish(registry)
        self.assertFalse(latest)
        self.assertEqual(registry.writes, ["1.2.3"])

    def test_new_version_advances_latest(self):
        registry = FakeRegistry(latest="1.2.2")
        self.assertTrue(self.publish(registry)[1])

    def test_invalid_latest_metadata_fails_instead_of_overwriting(self):
        registry = FakeRegistry(latest="development")
        with self.assertRaises(ValueError):
            self.publish(registry)
        self.assertNotIn("latest", registry.writes)

    def test_wrong_candidate_or_revision_is_rejected(self):
        registry = FakeRegistry()
        registry.manifests["candidate-123"] = manifest("sha256:wrong")
        with self.assertRaisesRegex(RuntimeError, "tested image"):
            self.publish(registry)
        self.assertEqual(registry.writes, [])
        registry = FakeRegistry()
        registry.metadata["sha256:tested"][
            "org.opencontainers.image.revision"
        ] = "wrong-commit"
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
            self.publish(registry)
        self.assertEqual(registry.writes, [])

    def test_invalid_versions(self):
        for value in ("v1.2.3", "1.2.3rc1", "1.2", "$(command)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_tuple(value)


class RegistryErrorTest(unittest.TestCase):
    def test_containerd_index_selects_amd64_and_ignores_attestations(self):
        registry = Registry.__new__(Registry)
        index = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "digest": "sha256:platform-image",
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "digest": "sha256:attestation",
                    "platform": {"os": "unknown", "architecture": "unknown"},
                },
            ],
        }
        expected = manifest("sha256:tested")
        with mock.patch.object(
            registry,
            "request",
            side_effect=[json.dumps(index).encode(), expected[0]],
        ) as request:
            self.assertEqual(registry.manifest("candidate-123"), expected)
        self.assertEqual(
            request.call_args.args, ("manifests/sha256:platform-image",)
        )

    def test_wrong_platform_index_is_rejected(self):
        registry = Registry.__new__(Registry)
        index = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "digest": "sha256:arm64",
                    "platform": {"os": "linux", "architecture": "arm64"},
                }
            ],
        }
        with mock.patch.object(
            registry, "request", return_value=json.dumps(index).encode()
        ):
            with self.assertRaisesRegex(
                RuntimeError, "exactly one linux/amd64"
            ):
                registry.manifest("candidate-123")

    def request_with_error(self, status, code):
        registry = Registry.__new__(Registry)
        registry.path = "owner/image"
        registry.token = "test-token"
        error = urllib.error.HTTPError(
            "https://ghcr.io/test",
            status,
            "test error",
            {},
            BytesIO(json.dumps({"errors": [{"code": code}]}).encode()),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            return registry.request("manifests/1.2.3")

    def test_missing_manifest_is_allowed(self):
        self.assertIsNone(self.request_with_error(404, "MANIFEST_UNKNOWN"))

    def test_denied_missing_repository_and_server_errors_are_not_absence(self):
        for status, code in (
            (401, "UNAUTHORIZED"),
            (403, "DENIED"),
            (404, "NAME_UNKNOWN"),
            (500, "UNKNOWN"),
        ):
            with (
                self.subTest(status=status),
                self.assertRaises(urllib.error.HTTPError),
            ):
                self.request_with_error(status, code)


if __name__ == "__main__":
    unittest.main()
