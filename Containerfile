# syntax=docker/dockerfile:1.7

ARG UBI_MINIMAL_IMAGE="registry.access.redhat.com/ubi9/ubi-minimal:9.8@sha256:7fbeae18dc9476399f565e68255f602a3374ea8614ba3d14843565131a13ff93"
ARG UBI_MICRO_IMAGE="registry.access.redhat.com/ubi9/ubi-micro:9.8@sha256:f332c99eb8f798a8486821c91937f10ad64ee83d7e739303be2df051040918f6"

FROM ${UBI_MINIMAL_IMAGE} AS builder

ARG TARGETARCH

# Every value below is a copy of artifacts/lakekeeper.lock.json. The build must
# never select "latest" or resolve a release at build time.
ARG LAKEKEEPER_VERSION="0.13.4"
ARG LAKEKEEPER_AMD64_URL="https://github.com/lakekeeper/lakekeeper/releases/download/v0.13.4/lakekeeper-x86_64-unknown-linux-gnu.tar.gz"
ARG LAKEKEEPER_AMD64_ARCHIVE_SHA256="1ee4c9f5e3409d91d61258d8d378a94a9ea9b16db2ba08c0ed0ed85b1dc3dd10"
ARG LAKEKEEPER_AMD64_BINARY_SHA256="52cdaa0be3724158ce7943f211fcff09a1ae451b5e88916a42b367bdaf1fd705"
ARG LAKEKEEPER_ARM64_URL="https://github.com/lakekeeper/lakekeeper/releases/download/v0.13.4/lakekeeper-aarch64-unknown-linux-gnu.tar.gz"
ARG LAKEKEEPER_ARM64_ARCHIVE_SHA256="14d52e4141b0494e79400e38a773b4682a0e3a98b7f3148943a6c09ca869abe0"
ARG LAKEKEEPER_ARM64_BINARY_SHA256="fea96fa11ecfff75a82892e70387f4abba02ab4a1ade5f3a40bc1afa63f20889"

# Acquire the locked release archive and admit it only after both the archive
# and the extracted binary match their reviewed digests. `docs/ARTIFACT-
# ACQUISITION.md` requires this download to move outside the build, and the
# build to run with networking disabled, before the first release.
# hadolint ignore=DL3041
RUN microdnf install -y tar gzip \
    && microdnf clean all \
    && case "${TARGETARCH}" in \
        amd64) \
            archive_url="${LAKEKEEPER_AMD64_URL}" ; \
            archive_sha256="${LAKEKEEPER_AMD64_ARCHIVE_SHA256}" ; \
            binary_sha256="${LAKEKEEPER_AMD64_BINARY_SHA256}" ; \
            ;; \
        arm64) \
            archive_url="${LAKEKEEPER_ARM64_URL}" ; \
            archive_sha256="${LAKEKEEPER_ARM64_ARCHIVE_SHA256}" ; \
            binary_sha256="${LAKEKEEPER_ARM64_BINARY_SHA256}" ; \
            ;; \
        *) \
            echo "Unsupported target architecture: ${TARGETARCH}" >&2 ; \
            exit 1 ; \
            ;; \
    esac \
    && mkdir -p /staging \
    && curl --fail --location --silent --show-error \
        --proto '=https' --tlsv1.2 \
        --output /staging/lakekeeper.tar.gz \
        "${archive_url}" \
    && printf '%s  /staging/lakekeeper.tar.gz\n' "${archive_sha256}" \
        > /staging/archive.sha256 \
    && sha256sum --check --strict /staging/archive.sha256 \
    && tar --extract --gzip \
        --file /staging/lakekeeper.tar.gz \
        --directory /staging \
        lakekeeper \
    && printf '%s  /staging/lakekeeper\n' "${binary_sha256}" \
        > /staging/binary.sha256 \
    && sha256sum --check --strict /staging/binary.sha256 \
    && rm -f /staging/lakekeeper.tar.gz /staging/archive.sha256 /staging/binary.sha256 \
    && chmod 0555 /staging/lakekeeper \
    && /staging/lakekeeper version

# Install the runtime dependency closure into a separate root. The UBI Micro
# final stage receives no package-management commands or builder caches. The
# locked binary needs only glibc (libc, libm, libresolv, the dynamic loader)
# and libgcc; ca-certificates and tzdata serve object-store and identity-
# provider TLS and timestamp handling.
# hadolint ignore=DL3041
RUN microdnf install -y dnf \
    && mkdir -p /runtime \
    && dnf install -y \
        --installroot=/runtime \
        --releasever=9 \
        --setopt=install_weak_deps=0 \
        --setopt=keepcache=0 \
        glibc \
        libgcc \
        ca-certificates \
        tzdata \
    && dnf clean all \
    && microdnf clean all \
    && rm -rf \
        /runtime/run/* \
        /runtime/tmp/* \
        /runtime/var/cache/dnf \
        /runtime/var/log/* \
        /runtime/var/tmp/*

FROM ${UBI_MICRO_IMAGE}

ARG LAKEKEEPER_VERSION="0.13.4"

LABEL org.opencontainers.image.title="Lakekeeper on Red Hat UBI 9" \
      org.opencontainers.image.description="A security-oriented, rootless Lakekeeper Apache Iceberg REST catalog built on Red Hat UBI 9 Micro" \
      org.opencontainers.image.source="https://github.com/datopsis/lakekeeper-ubi" \
      org.opencontainers.image.documentation="https://github.com/datopsis/lakekeeper-ubi#readme" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Datopsis" \
      org.opencontainers.image.version="${LAKEKEEPER_VERSION}" \
      io.datopsis.lakekeeper.upstream-version="${LAKEKEEPER_VERSION}"

COPY --from=builder /runtime/ /
COPY --from=builder --chown=0:0 --chmod=0555 /staging/lakekeeper /usr/local/bin/lakekeeper
COPY --chown=0:0 --chmod=0555 container/entrypoint.sh /usr/local/bin/lakekeeper-entrypoint

# LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY is added by this image, not by upstream
# Lakekeeper, and defaults to true so a deployment cannot silently fall back to
# the publicly known default secret encryption key.
#
# The default is applied in the entrypoint rather than declared here. Declaring
# it as ENV adds nothing at runtime, and configuration scanners reasonably flag
# any ENV whose name looks like a credential. Suppressing that rule for this
# file would also hide a genuinely leaked secret, and renaming the variable to
# evade the heuristic would make it less clear to operators. See
# docs/CONFIGURATION.md.
ENV LANG="C.UTF-8" \
    TZ="UTC"

USER 999:0

# 8181 serves the Iceberg REST and management APIs. 9000 serves metrics and is
# expected to stay on an internal network.
EXPOSE 8181 9000

# The health probe calls the binary directly rather than through the
# entrypoint, so a health check never depends on the configuration guard.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["lakekeeper", "healthcheck", "-s"]

STOPSIGNAL SIGTERM

# The entrypoint validates configuration as the unprivileged runtime identity
# and then execs the server, so Lakekeeper still runs as PID 1.
ENTRYPOINT ["/usr/local/bin/lakekeeper-entrypoint", "lakekeeper"]
CMD ["serve"]
