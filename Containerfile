# syntax=docker/dockerfile:1.7

ARG UBI_MINIMAL_IMAGE="registry.access.redhat.com/ubi9/ubi-minimal:9.8@sha256:7fbeae18dc9476399f565e68255f602a3374ea8614ba3d14843565131a13ff93"
ARG UBI_MICRO_IMAGE="registry.access.redhat.com/ubi9/ubi-micro:9.8@sha256:f332c99eb8f798a8486821c91937f10ad64ee83d7e739303be2df051040918f6"

# The Micro filesystem is the starting point for the runtime root, so package
# installation resolves against the database the final stage actually has. An
# empty installroot would instead reinstall a base system that is already
# present, inflating both the image and its package inventory.
FROM ${UBI_MICRO_IMAGE} AS microbase

FROM ${UBI_MINIMAL_IMAGE} AS builder

COPY --from=microbase / /runtime
# `bundle` is a named build context holding the verified upstream binary and
# the locked runtime packages, produced by scripts/fetch-artifacts.sh.
# hadolint ignore=DL3022
COPY --from=bundle rpms/ /rpms/

# Install the locked packages with no repository, no dependency resolution,
# and no network. Signatures are checked against the Red Hat keys already in
# the Micro RPM database, so publisher verification happens here even though
# the download happened earlier and elsewhere.
RUN rpmkeys --root /runtime --checksig /rpms/*.rpm \
    && rpm --root /runtime --upgrade --replacepkgs --quiet /rpms/*.rpm \
    && rm -rf \
        /runtime/run/* \
        /runtime/tmp/* \
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
# The binary arrives from the same verified bundle. A plain `podman build .`
# fails here, which is the intended behavior: the image must not be assemblable
# from unverified inputs.
# DL3022 expects --from to name a build stage. `bundle` is a named build
# context, which hadolint does not model; there is no stage alias to use
# instead, and routing the binary through a stage would put it back in the
# default context this indirection exists to avoid.
# hadolint ignore=DL3022
COPY --from=bundle --chown=0:0 --chmod=0555 lakekeeper /usr/local/bin/lakekeeper
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
