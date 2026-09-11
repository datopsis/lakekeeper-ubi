#!/usr/bin/env bash
# Negative tests for the artifact admission gate.
#
# scripts/verify-bundle.sh is what stands between a downloaded file and an
# image. These cases corrupt a known-good bundle in one specific way each and
# require the gate to refuse. A gate that has never been shown to reject is not
# evidence of anything.
#
# No container runtime is needed: the gate works on local files.
set -Eeuo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
verify="${repository_root}/scripts/verify-bundle.sh"
architecture="${ARCHITECTURE:-}"

if test -z "${architecture}"; then
    case "$(uname -m)" in
        x86_64 | amd64) architecture="amd64" ;;
        aarch64 | arm64) architecture="arm64" ;;
        *) echo "unsupported host architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

source_bundle="${BUNDLE_DIR:-${repository_root}/.artifact-bundle/${architecture}}"
test -d "${source_bundle}" || {
    echo "no bundle at ${source_bundle}; run scripts/fetch-artifacts.sh first" >&2
    exit 1
}

workdir="$(mktemp -d)"
cleanup() {
    rm -rf -- "${workdir}"
}
trap cleanup EXIT

failures=0

# Each case gets an untouched copy, so one case cannot mask another.
fresh_bundle() {
    local name="$1"
    local target="${workdir}/${name}"
    rm -rf -- "${target}"
    cp -r -- "${source_bundle}" "${target}"
    chmod -R u+w -- "${target}"
    printf '%s\n' "${target}"
}

expect_rejected() {
    local description="$1"
    local bundle="$2"
    local output
    if output="$("${verify}" --arch "${architecture}" --bundle-dir "${bundle}" 2>&1)"; then
        echo "FAIL: the gate admitted a bundle with ${description}" >&2
        failures=$((failures + 1))
        return
    fi
    if ! grep -qi 'error:' <<< "${output}"; then
        echo "FAIL: rejection for ${description} did not explain itself" >&2
        printf '%s\n' "${output}" >&2
        failures=$((failures + 1))
        return
    fi
    echo "ok: rejected ${description}"
}

expect_admitted() {
    local description="$1"
    local bundle="$2"
    if "${verify}" --arch "${architecture}" --bundle-dir "${bundle}" >/dev/null 2>&1; then
        echo "ok: admitted ${description}"
        return
    fi
    echo "FAIL: the gate rejected ${description}" >&2
    "${verify}" --arch "${architecture}" --bundle-dir "${bundle}" >&2 || true
    failures=$((failures + 1))
}

# A known-good bundle must pass, or every rejection below proves nothing.
expect_admitted "an unmodified bundle" "$(fresh_bundle control)"

# A single flipped byte must not reach an image.
bundle="$(fresh_bundle tampered)"
printf 'x' | dd of="${bundle}/lakekeeper" bs=1 seek=4096 conv=notrunc status=none
expect_rejected "a tampered binary" "${bundle}"

# Truncation changes the size before it changes anything else.
bundle="$(fresh_bundle truncated)"
truncate -s -1 "${bundle}/lakekeeper"
expect_rejected "a truncated binary" "${bundle}"

# An extra file in the bundle would be copied into the build context.
bundle="$(fresh_bundle extra_member)"
printf 'unexpected\n' > "${bundle}/extra-file"
expect_rejected "an unexpected extra file" "${bundle}"

# A missing binary must fail loudly rather than produce an empty image layer.
bundle="$(fresh_bundle missing_binary)"
rm -f -- "${bundle}/lakekeeper"
expect_rejected "a missing binary" "${bundle}"

# A bundle with no manifest has unknown provenance.
bundle="$(fresh_bundle missing_manifest)"
rm -f -- "${bundle}/bundle.json"
expect_rejected "a missing manifest" "${bundle}"

# A bundle fetched before a lock update must not be reused silently.
bundle="$(fresh_bundle stale_version)"
python3 - "${bundle}/bundle.json" <<'PYTHON'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["upstreamVersion"] = "0.0.1-stale"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
PYTHON
expect_rejected "a bundle left over from an older lock" "${bundle}"

# The wrong architecture's binary must not be accepted for this architecture.
other_architecture="arm64"
test "${architecture}" != "arm64" || other_architecture="amd64"
other_bundle="${repository_root}/.artifact-bundle/${other_architecture}"
if test -d "${other_bundle}"; then
    expect_rejected "a ${other_architecture} binary offered as ${architecture}" "${other_bundle}"
else
    echo "skip: no ${other_architecture} bundle present to test architecture confusion"
fi

# The cases above all fail at the digest, because that check runs first. The
# ELF properties in the lock therefore defend against something different: a
# lock whose recorded facts drift from the bytes it names, which is an authoring
# mistake rather than tampering. Exercise that by doctoring a copy of the lock
# and leaving the bundle untouched.
doctored_lock="${workdir}/doctored-lock.json"
source_lock="${repository_root}/artifacts/lakekeeper.lock.json"

doctor_lock() {
    ARCHITECTURE="${architecture}" FIELD="$1" VALUE="$2" \
        SOURCE="${source_lock}" TARGET="${doctored_lock}" python3 - <<'PYTHON'
import json
import os

lock = json.load(open(os.environ["SOURCE"], encoding="utf-8"))
entry = lock["architectures"][os.environ["ARCHITECTURE"]]
field = os.environ["FIELD"]
value = os.environ["VALUE"]
if field == "buildId":
    entry["binary"]["buildId"] = value
elif field == "neededSharedLibraries":
    entry["runtimeRequirements"][field] = value.split(",")
else:
    entry["runtimeRequirements"][field] = value
with open(os.environ["TARGET"], "w", encoding="utf-8") as handle:
    json.dump(lock, handle, indent=2)
PYTHON
}

expect_rejected_by_drift() {
    local description="$1"
    local bundle
    bundle="$(fresh_bundle drift)"
    if LOCK_FILE="${doctored_lock}" "${verify}" --arch "${architecture}" \
        --bundle-dir "${bundle}" >/dev/null 2>&1; then
        echo "FAIL: the gate admitted a bundle despite ${description}" >&2
        failures=$((failures + 1))
        return
    fi
    echo "ok: rejected ${description}"
}

doctor_lock maxGlibcSymbolVersion "2.99"
expect_rejected_by_drift "a lock recording the wrong glibc requirement"

doctor_lock buildId "0000000000000000000000000000000000000000"
expect_rejected_by_drift "a lock recording the wrong build ID"

doctor_lock neededSharedLibraries "libc.so.6,libssl.so.3"
expect_rejected_by_drift "a lock recording the wrong shared libraries"

test "${failures}" -eq 0 || {
    echo "${failures} acquisition gate case(s) failed" >&2
    exit 1
}

echo "Artifact acquisition gate rejected every tampered bundle"
