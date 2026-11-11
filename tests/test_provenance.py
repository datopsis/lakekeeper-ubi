"""Regression coverage for missing, inherited and incorrect image provenance."""

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provenance", ROOT / "tests/image-provenance.py")
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.revision = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        self.lock_sha = hashlib.sha256((ROOT / "artifacts/lakekeeper.lock.json").read_bytes()).hexdigest()
        self.image = {
            "Id": "sha256:test-image",
            "Architecture": "amd64",
            "Config": {"Labels": {
                provenance.REVISION_LABEL: self.revision,
                provenance.LOCK_LABEL: self.lock_sha,
            }},
        }

    def test_both_architectures_report_inspected_values(self):
        for architecture in ("amd64", "arm64"):
            with self.subTest(architecture=architecture):
                self.image["Architecture"] = architecture
                evidence = provenance.verify(self.image, self.revision, self.lock_sha, architecture)
                self.assertEqual(evidence["architecture"], architecture)
                self.assertEqual(evidence["image_id"], self.image["Id"])
                self.assertEqual(evidence[provenance.REVISION_LABEL], self.revision)
                self.assertEqual(evidence[provenance.LOCK_LABEL], self.lock_sha)

    def test_rejects_missing_empty_inherited_and_wrong_labels(self):
        for label in (provenance.REVISION_LABEL, provenance.LOCK_LABEL):
            for value in (None, "", "9d7bd388a99de116058bd54b77737e2863cb3d45", "0" * 64):
                with self.subTest(label=label, value=value):
                    image = copy.deepcopy(self.image)
                    if value is None:
                        del image["Config"]["Labels"][label]
                    else:
                        image["Config"]["Labels"][label] = value
                    with self.assertRaisesRegex(ValueError, label):
                        provenance.verify(image, self.revision, self.lock_sha, "amd64")

    def test_rejects_absent_labels(self):
        for labels in (None, {}):
            self.image["Config"]["Labels"] = labels
            with self.assertRaises(ValueError):
                provenance.verify(self.image, self.revision, self.lock_sha, "amd64")

    def test_rejects_wrong_architecture(self):
        with self.assertRaisesRegex(ValueError, "architecture"):
            provenance.verify(self.image, self.revision, self.lock_sha, "arm64")

    def test_metadata_uses_repo_head_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.check_output(
                [str(ROOT / "scripts/build-metadata.sh")], cwd=directory, text=True
            )
        self.assertEqual(output, f"SOURCE_REVISION={self.revision}\nLOCK_SHA256={self.lock_sha}\n")

    def test_metadata_hashes_exact_selected_lock_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "lock.json"
            # Whitespace must affect the digest: do not hash reserialized JSON,
            # the architecture subsection, or the downloaded bundle manifest.
            for content in (b'{"architectures": {}}\n', b'{ "architectures": {} }\n'):
                lock.write_bytes(content)
                output = subprocess.check_output(
                    [str(ROOT / "scripts/build-metadata.sh")], text=True,
                    env={**os.environ, "LOCK_FILE": str(lock)},
                )
                self.assertIn(f"LOCK_SHA256={hashlib.sha256(content).hexdigest()}\n", output)

    def test_metadata_fails_without_source_or_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            for overrides in ({"REPOSITORY_ROOT": directory}, {"LOCK_FILE": f"{directory}/missing"}):
                with self.subTest(overrides=overrides):
                    result = subprocess.run(
                        [str(ROOT / "scripts/build-metadata.sh")], text=True,
                        env={**os.environ, **overrides}, capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
