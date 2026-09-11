#!/usr/bin/env bash
# Prove the image contains everything the application needs at runtime.
#
# tests/check-runtime-requirements.sh compares the binary against the lock.
# This checks something different: that the assembled image can actually
# satisfy the binary, including the parts no dependency list mentions.
#
# The failure this defends against is specific. `readelf -d` lists only
# DT_NEEDED entries. A process can still fail at runtime on libraries loaded
# with dlopen, which is exactly how glibc resolves hostnames: a container that
# passes every static check will still fail to reach its database if the NSS
# modules are absent. Minimized images get this wrong routinely.
set -Eeuo pipefail

runtime="${CONTAINER_RUNTIME:-podman}"
image="${IMAGE:-localhost/lakekeeper-ubi9:development}"
architecture="${ARCHITECTURE:-}"

if test -z "${architecture}"; then
    case "$(uname -m)" in
        x86_64 | amd64) architecture="amd64" ;;
        aarch64 | arm64) architecture="arm64" ;;
        *) echo "unsupported host architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

case "${architecture}" in
    amd64) loader="/usr/lib64/ld-linux-x86-64.so.2" ;;
    arm64) loader="/usr/lib/ld-linux-aarch64.so.1" ;;
    *) echo "unsupported architecture: ${architecture}" >&2; exit 1 ;;
esac

failures=0

fail() {
    echo "FAIL: $*" >&2
    failures=$((failures + 1))
}

# The image has no ldd, so the dynamic loader is asked directly. An unresolved
# library appears here as "not found" rather than at first start.
resolution="$("${runtime}" run --rm --entrypoint "${loader}" "${image}" \
    --list /usr/local/bin/lakekeeper 2>&1)"

if grep -q "not found" <<< "${resolution}"; then
    echo "${resolution}" >&2
    fail "the image cannot resolve every library the binary needs"
else
    echo "ok: every needed library resolves inside the image"
fi

# Each library the lock records must appear as resolved, not merely absent from
# the error output.
while read -r library; do
    case "${library}" in
        ld-*) continue ;;
    esac
    if ! grep -q "${library} => /" <<< "${resolution}"; then
        fail "${library} did not resolve to a path inside the image"
    fi
done < <(ARCHITECTURE="${architecture}" python3 -c '
import json
import os

lock = json.load(open("artifacts/lakekeeper.lock.json", encoding="utf-8"))
entry = lock["architectures"][os.environ["ARCHITECTURE"]]["runtimeRequirements"]
for library in entry["neededSharedLibraries"]:
    print(library)
')

# Hostname resolution is a dlopen path, so it is invisible to every check that
# reads the binary. Lakekeeper reaches PostgreSQL, object storage, and identity
# providers by name, so this is load-bearing.
# The variables expand in the inner container shell, not this script.
# shellcheck disable=SC2016
nss_report="$("${runtime}" run --rm --entrypoint sh "${image}" -c '
    test -f /etc/nsswitch.conf || echo "missing:/etc/nsswitch.conf"
    test -f /etc/hosts || echo "missing:/etc/hosts"
    test -f /etc/services || echo "missing:/etc/services"
    for module in libnss_dns libnss_files; do
        ls /usr/lib64/${module}.so.2 >/dev/null 2>&1 || echo "missing:${module}"
    done
    echo "done"
')"
if grep -q '^missing:' <<< "${nss_report}"; then
    grep '^missing:' <<< "${nss_report}" >&2
    fail "name resolution support is incomplete"
else
    echo "ok: name resolution support is present"
fi

# Outbound TLS depends on trust material that nothing else in the suite checks.
# An empty or unparsable bundle would only surface when the catalog first tried
# to reach object storage or an identity provider.
# The variables expand in the inner container shell, not this script.
# shellcheck disable=SC2016
trust_report="$("${runtime}" run --rm --entrypoint sh "${image}" -c '
    bundle=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
    test -r "${bundle}" || { echo "missing"; exit 0; }
    printf "bytes:%s certs:%s\n" \
        "$(wc -c < "${bundle}")" \
        "$(grep -c "BEGIN CERTIFICATE" "${bundle}")"
')"
if grep -q missing <<< "${trust_report}"; then
    fail "the image has no readable TLS trust bundle"
else
    certificate_count="${trust_report##*certs:}"
    if test "${certificate_count}" -lt 50; then
        fail "the TLS trust bundle holds only ${certificate_count} certificates"
    else
        echo "ok: TLS trust bundle holds ${certificate_count} certificates"
    fi
fi

# Time zone data is installed deliberately, because the base image records the
# package as present while shipping none of its files.
if "${runtime}" run --rm --entrypoint sh "${image}" -c \
    'test -f /usr/share/zoneinfo/UTC && test -d /usr/share/zoneinfo/America'; then
    echo "ok: time zone data is present"
else
    fail "time zone data is missing despite tzdata being recorded as installed"
fi

test "${failures}" -eq 0 || {
    echo "${failures} runtime dependency check(s) failed" >&2
    exit 1
}

echo "Runtime dependencies satisfied for ${image}"
