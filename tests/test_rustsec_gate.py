"""Shipped-code classification must not confuse host tools with target crates."""

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "rustsec_gate", Path(__file__).resolve().parents[1] / "scripts/rustsec_gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class RustSecClassificationTest(unittest.TestCase):
    def fixture(self):
        def unit(package, kind, dependencies):
            return {"pkg_id": package, "target": {"name": package, "kind": [kind]},
                    "mode": "build", "dependencies": [{"index": i} for i in dependencies]}

        units = [unit("lakekeeper", "bin", [1, 2, 3]),
                 unit("runtime", "lib", [4]),
                 unit("derive", "proc-macro", [5]),
                 unit("build-script", "custom-build", [6]),
                 unit("shared", "lib", []), unit("macro-helper", "lib", [4]),
                 unit("build-helper", "lib", [])]
        packages = [{"id": u["pkg_id"], "name": u["pkg_id"], "version": "1.0.0",
                     "source": "registry+test"} for u in units]
        return {"version": 1, "roots": [0], "units": units}, {"packages": packages}

    def test_excludes_host_subtrees_but_keeps_shared_runtime_crate(self):
        graph, metadata = self.fixture()
        selected = gate.runtime_packages(graph, metadata)
        self.assertEqual({p[0] for p in selected}, {"lakekeeper", "runtime", "shared"})

    def test_missing_root_or_identity_blocks(self):
        graph, metadata = self.fixture()
        graph["roots"] = []
        with self.assertRaises(ValueError):
            gate.runtime_packages(graph, metadata)
        graph["roots"] = [0]
        metadata["packages"] = []
        with self.assertRaises(KeyError):
            gate.runtime_packages(graph, metadata)

    def test_partition_uses_source_as_well_as_version(self):
        packages = [{"name": "xml", "version": "1.0.0", "source": s}
                    for s in ("registry+test", "git+fork")]
        shipped, other = gate.partition_lock(
            {"package": packages}, {("xml", "1.0.0", "git+fork")})
        self.assertEqual(shipped, packages[1:])
        self.assertEqual(other, packages[:1])
        with self.assertRaises(ValueError):
            gate.partition_lock({"package": []}, {("xml", "1.0.0", None)})

    def test_git_tag_query_encoding_preserves_commit_identity(self):
        raw = "git+https://example.test/nats?tag=async-nats/v1#abc123"
        encoded = "git+https://example.test/nats?tag=async-nats%2Fv1#abc123"
        self.assertEqual(gate.canonical_source(raw), encoded)
        self.assertNotEqual(gate.canonical_source(raw), encoded.replace("abc123", "def456"))


if __name__ == "__main__":
    unittest.main()
