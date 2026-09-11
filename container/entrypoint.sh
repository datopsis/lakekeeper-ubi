#!/bin/sh
# Refuse to start without a secret encryption key, when configured to do so.
#
# Upstream Lakekeeper treats LAKEKEEPER__PG_ENCRYPTION_KEY as optional: when it
# is unset the server starts anyway, logs a single warning, and encrypts stored
# storage credentials with a default key that is published in the upstream
# source. A deployment in that state looks healthy indefinitely while holding
# credentials that anyone can decrypt.
#
# This guard converts that silent degradation into a startup failure. It is
# controlled by LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY and documented in
# docs/CONFIGURATION.md.
#
# This is not a privilege transition. The script runs as the same unprivileged
# identity the container was given, never changes user or group, and replaces
# itself with `exec` so the Lakekeeper process becomes PID 1 and receives
# signals directly.
set -eu

# sysexits.h EX_CONFIG: the failure is configuration, not a crash.
readonly EXIT_CONFIGURATION=78
readonly TOGGLE_NAME="LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY"
readonly KEY_NAME="LAKEKEEPER__PG_ENCRYPTION_KEY"

# The value upstream falls back to when the variable is unset. Setting it
# explicitly is exactly as unsafe as leaving it unset, and upstream does not
# warn in that case: the warning fires only on an absent variable. Someone who
# copies a chart default or an example therefore gets no signal at all.
#
# This is version-specific. Re-check it when the locked upstream version
# changes; a silently renamed default would make this check pass for the wrong
# reason.
readonly UPSTREAM_DEFAULT_KEY="This is unsafe, please set a proper key"

fail() {
    printf 'lakekeeper-ubi: %s\n' "$1" >&2
    shift
    for line in "$@"; do
        printf 'lakekeeper-ubi:   %s\n' "${line}" >&2
    done
    exit "${EXIT_CONFIGURATION}"
}

requested="$(printf '%s' "${LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY:-true}" \
    | tr '[:upper:]' '[:lower:]')"

case "${requested}" in
    true | 1 | yes | on)
        require_key="yes"
        ;;
    false | 0 | no | off)
        require_key="no"
        ;;
    *)
        # An unreadable toggle is treated as a request for the safe behavior
        # rather than silently ignored.
        fail "${TOGGLE_NAME} is not a recognized boolean." \
            "Use true or false. Refusing to start rather than guessing."
        ;;
esac

# The entrypoint is invoked with the binary as its first argument, so the
# subcommand is the first argument that is not the binary itself.
subcommand=""
for argument in "$@"; do
    case "${argument}" in
        lakekeeper | */lakekeeper)
            continue
            ;;
        *)
            subcommand="${argument}"
            break
            ;;
    esac
done

# Commands that never read or write encrypted secrets stay usable for
# diagnostics even when the key is absent. Anything not listed here, including
# a subcommand added by a future upstream release, is treated as requiring the
# key so that the default is the safe one.
case "${subcommand}" in
    version | healthcheck | help | management-openapi | generic-table-openapi \
        | -h | --help | -V | --version)
        needs_key="no"
        ;;
    *)
        needs_key="yes"
        ;;
esac

if test "${require_key}" = "yes" && test "${needs_key}" = "yes"; then
    # Whitespace is stripped so that a variable set to spaces is still empty.
    # The value itself is never printed, logged, or echoed.
    if test -z "$(printf '%s' "${LAKEKEEPER__PG_ENCRYPTION_KEY:-}" \
        | tr -d '[:space:]')"; then
        fail "${KEY_NAME} is unset or empty." \
            "Lakekeeper would otherwise start and encrypt stored storage" \
            "credentials with a publicly known default key." \
            "Set ${KEY_NAME} to a unique secret value." \
            "To accept upstream behavior instead, set ${TOGGLE_NAME}=false." \
            "See https://github.com/datopsis/lakekeeper-ubi#secret-encryption-key"
    fi

    # Set to the published default, the key is public knowledge, so the value
    # is compared rather than only its presence. The comparison names no
    # secret: the value it matches is already in upstream's documentation.
    if test "${LAKEKEEPER__PG_ENCRYPTION_KEY}" = "${UPSTREAM_DEFAULT_KEY}"; then
        fail "${KEY_NAME} is set to the publicly known upstream default." \
            "That is exactly as unsafe as leaving it unset, and upstream does" \
            "not warn about it." \
            "Set ${KEY_NAME} to a unique secret value." \
            "To accept upstream behavior instead, set ${TOGGLE_NAME}=false." \
            "See https://github.com/datopsis/lakekeeper-ubi#secret-encryption-key"
    fi
fi

exec "$@"
