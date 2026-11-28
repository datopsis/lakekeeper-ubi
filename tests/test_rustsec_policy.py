"""Policy decisions and scheduled tracking, without network or issue writes."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rustsec_policy as policy
import track_unpatched_rustsec as tracker


def finding(patched=(), informational=None):
    return dict(package=dict(name="example", version="1.0.0", source="registry+test"),
                advisory=dict(id="RUSTSEC-2000-0001", informational=informational),
                versions=dict(patched=list(patched), unaffected=[]))


def reports(patched=(), guidance="guidance-1"):
    result = {}
    for arch in ("amd64", "arm64"):
        f = finding(patched, "unmaintained")
        result[arch] = dict(runtime=[policy.classify(f)],
                            packages={("example", "1.0.0", "registry+test")},
                            catalog={"RUSTSEC-2000-0001": dict(
                                package="example", patched=list(patched),
                                informational="unmaintained", withdrawn=None,
                                guidance=guidance, guidance_sha256=guidance)})
    return result


class PolicyTests(unittest.TestCase):
    def test_fixable_blocks_for_every_advisory_type(self):
        for kind in (None, "unsound", "unmaintained", "notice", "future-type"):
            with self.subTest(kind=kind):
                row = policy.classify(finding([">=2.0.0"], kind))
                self.assertEqual(row["decision"], "block")
                self.assertEqual(row["patched"], [">=2.0.0"])

    def test_no_patch_reports_for_every_advisory_type(self):
        for kind in (None, "unsound", "unmaintained", "notice", "future-type"):
            with self.subTest(kind=kind):
                row = policy.classify(finding([], kind))
                self.assertEqual(row["decision"], "report")
                self.assertEqual(row["reason"], "no patched version available")

    def test_build_only_and_unshipped_subjects_never_block_findings(self):
        self.assertEqual(policy.classify(finding([">=2"]), "build-only-or-unselected")["decision"], "report")
        self.assertEqual(policy.classify(finding([">=2"]), report_only=True)["decision"], "report")

    def test_missing_or_malformed_patch_metadata_cannot_pass(self):
        for versions in (None, {}, {"patched": None}, {"patched": ">=2"},
                         {"patched": [""]}, {"patched": [None]}):
            f = finding()
            f["versions"] = versions
            with self.subTest(versions=versions), self.assertRaises(ValueError):
                policy.classify(f)

    def test_yanked_keeps_its_existing_independent_check(self):
        f = dict(package=dict(name="example", version="1", source=None))
        self.assertEqual(policy.classify(f)["decision"], "block")
        self.assertEqual(policy.classify(f, "build-only-or-unselected")["decision"], "report")

    def test_patch_range_whitespace_and_order_do_not_change_policy(self):
        self.assertEqual(policy.patched_ranges(dict(patched=[">= 2", "^1.2", ">=2"])), [">=2", "^1.2"])

    def test_catalog_includes_replacement_guidance_and_version_updates(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            p = root / "crates/example/RUSTSEC-2000-0001.md"
            p.parent.mkdir(parents=True)
            text = ('```toml\n[advisory]\nid="RUSTSEC-2000-0001"\npackage="example"\n'
                    'informational="unmaintained"\n[versions]\npatched=[]\n```\n'
                    '# Unmaintained\nReplace with successor.\n')
            p.write_text(text)
            old = policy.advisory_catalog(root)["RUSTSEC-2000-0001"]
            self.assertIn("successor", old["guidance"])
            p.write_text(text.replace("successor", "new-successor"))
            self.assertNotEqual(old["guidance_sha256"], policy.advisory_catalog(root)["RUSTSEC-2000-0001"]["guidance_sha256"])
            p.write_text(text.replace("patched=[]", 'patched=[">=2"]'))
            self.assertEqual(policy.advisory_catalog(root)["RUSTSEC-2000-0001"]["patched"], [">=2"])


class TrackerTests(unittest.TestCase):
    def issue(self, data=None):
        data = data or reports()
        rows = tracker.evolve(data, [])
        return dict(number=7, body=tracker.render(rows, data, "old-run")[0], state="open")

    def test_one_issue_created_with_both_architectures_and_guidance(self):
        call = Mock(side_effect=[[], {}])
        tracker.update("owner/repo", reports(), "run", call)
        self.assertEqual(call.call_args.args[1:3], ("issues", "POST"))
        body = call.call_args.args[3]["body"]
        self.assertIn("amd64", body)
        self.assertIn("arm64", body)
        self.assertIn("guidance-1", body)
        self.assertEqual(len(tracker.read_state(body)), 2)

    def test_same_set_has_no_comment_for_new_run_or_db_order(self):
        issue = self.issue()
        for status in ("open", "closed"):
            call = Mock(return_value=[[dict(issue, state=status)]])
            tracker.update("owner/repo", reports(), "new-run", call)
            self.assertFalse(any("/comments" in c.args[1] for c in call.call_args_list))
            self.assertEqual(call.call_count, 1 if status == "open" else 2)

    def test_unrelated_new_fixable_finding_does_not_notify(self):
        data = reports()
        f = finding([">=2"])
        f["advisory"]["id"] = "RUSTSEC-2000-0002"
        for report in data.values():
            report["runtime"].append(policy.classify(f))
        call = Mock(return_value=[[self.issue()]])
        tracker.update("owner/repo", data, "new-run", call)
        self.assertEqual(call.call_count, 1)

    def test_fix_and_replacement_changes_notify_once(self):
        issue = self.issue()
        data = reports([">=2.0.0"], "new replacement")
        call = Mock(side_effect=[[[issue]], [], {}, {}])
        tracker.update("owner/repo", data, "run", call)
        comment = call.call_args_list[2].args[3]["body"]
        self.assertIn("FIX NOW AVAILABLE", comment)
        self.assertIn("REMEDIATION/REPLACEMENT GUIDANCE CHANGED", comment)
        self.assertEqual(call.call_args_list[3].args[1:3], ("issues/7", "PATCH"))
        updated = dict(issue, body=call.call_args_list[3].args[3]["body"])
        call = Mock(return_value=[[updated]])
        tracker.update("owner/repo", data, "next-run", call)
        self.assertEqual(call.call_count, 1)

    def test_fix_detected_even_after_finding_disappears(self):
        issue = self.issue()
        data = reports([">=2"])
        for report in data.values():
            report["runtime"] = []
            report["packages"] = set()
        call = Mock(side_effect=[[[issue]], [], {}, {}])
        tracker.update("owner/repo", data, "run", call)
        self.assertIn("FIX NOW AVAILABLE", call.call_args_list[2].args[3]["body"])
        self.assertIn("no-longer-shipped", call.call_args_list[3].args[3]["body"])

    def test_replacement_only_change_notifies_without_claiming_a_patch(self):
        call = Mock(side_effect=[[[self.issue()]], [], {}, {}])
        tracker.update("owner/repo", reports(guidance="a replacement was added"), "run", call)
        comment = call.call_args_list[2].args[3]["body"]
        self.assertIn("REMEDIATION/REPLACEMENT GUIDANCE CHANGED", comment)
        self.assertNotIn("FIX NOW AVAILABLE", comment)

    def test_posted_comment_then_failed_body_update_does_not_duplicate(self):
        issue = self.issue()
        data = reports([">=2"])
        rows = tracker.evolve(data, tracker.read_state(issue["body"]))
        body = tracker.render(rows, data, "run")[0]
        call = Mock(side_effect=[[[issue]], [[dict(body=body)]], {}])
        tracker.update("owner/repo", data, "run", call)
        self.assertFalse(any(c.args[2:3] == ("POST",) for c in call.call_args_list))
        self.assertEqual(call.call_args.args[1:3], ("issues/7", "PATCH"))

    def test_duplicate_issues_or_missing_state_fail_before_writes(self):
        issue = self.issue()
        for pages in ([[issue, issue]], [[dict(issue, body=tracker.MARKER)]]):
            call = Mock(return_value=pages)
            with self.assertRaises(ValueError):
                tracker.update("owner/repo", reports(), "run", call)
            self.assertEqual(call.call_count, 1)

    def test_missing_historical_advisory_cannot_claim_resolution(self):
        issue = self.issue()
        data = reports()
        data["amd64"]["catalog"] = {}
        call = Mock(return_value=[[issue]])
        with self.assertRaises(KeyError):
            tracker.update("owner/repo", data, "run", call)
        self.assertEqual(call.call_count, 1)

    def test_pr_and_manual_events_cannot_write_issues(self):
        for event, ref in (("pull_request", "refs/pull/28/merge"),
                           ("workflow_dispatch", "refs/heads/main"),
                           ("schedule", "refs/heads/feature")):
            with patch.dict(os.environ, GITHUB_EVENT_NAME=event, GITHUB_REF=ref), \
                    patch.object(sys, "argv", ["tracker", "/missing"]), \
                    patch.object(tracker, "native_reports") as read:
                with self.assertRaises(ValueError):
                    tracker.main()
                read.assert_not_called()

    def write_report(self, root, arch):
        directory = root / arch / "security-results/rustsec"
        directory.mkdir(parents=True)
        raw = dict(vulnerabilities=dict(list=[], count=0), warnings={})
        data = reports()[arch]
        content = (json.dumps(data["catalog"]) + "\n").encode()
        raw_bytes = json.dumps(raw).encode()
        (directory / "advisory-catalog.json").write_bytes(content)
        (directory / "shipped.json").write_bytes(raw_bytes)
        (directory / "shipped.Cargo.lock").write_text('version=4\n[[package]]\nname="example"\nversion="1.0.0"\n')
        evidence = dict(architecture=arch, admissionBlocking=True, advisoryDatabaseCommit="db")
        (directory / "evidence.json").write_text(json.dumps(evidence))
        report = dict(schema_version=1, policy_version=policy.POLICY_VERSION, complete=True,
                      architecture=arch, admissionBlocking=True, advisoryDatabaseCommit="db",
                      advisoryCatalogSha256=hashlib.sha256(content).hexdigest(),
                      shippedReportSha256=hashlib.sha256(raw_bytes).hexdigest(), runtime=[], blocked=False)
        (directory / "policy.json").write_text(json.dumps(report))
        return directory

    def test_missing_duplicate_tampered_or_incomplete_native_reports_fail(self):
        for mutation in ("missing", "duplicate", "hash", "incomplete", "unshipped", "raw", "provenance"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as work:
                root = Path(work)
                self.write_report(root, "amd64")
                if mutation != "missing":
                    p = self.write_report(root, "arm64")
                    if mutation == "duplicate":
                        import shutil
                        shutil.copytree(p, root / "duplicate/rustsec")
                    elif mutation == "hash":
                        (p / "shipped.json").write_text("{}")
                    elif mutation == "provenance":
                        (p / "evidence.json").write_text(json.dumps(dict(
                            architecture="amd64", admissionBlocking=True, advisoryDatabaseCommit="db")))
                    else:
                        value = json.loads((p / "policy.json").read_text())
                        value.update({"complete": False} if mutation == "incomplete" else
                                     {"admissionBlocking": False} if mutation == "unshipped" else
                                     {"runtime": [policy.classify(finding())]})
                        (p / "policy.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    tracker.native_reports(root)
        with tempfile.TemporaryDirectory() as work:
            for arch in ("amd64", "arm64"):
                self.write_report(Path(work), arch)
            self.assertEqual(set(tracker.native_reports(Path(work))), {"amd64", "arm64"})


if __name__ == "__main__":
    unittest.main()
