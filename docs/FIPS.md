# FIPS analysis

Status: analysis only. **This project makes no FIPS validation claim, and the
current image cannot support one.** This document exists so that the question
is answered with evidence rather than re-litigated, and so that a future claim,
if one is ever made, has a defined boundary.

## The question people actually ask

"Is this image FIPS compliant?" is not answerable as asked, because FIPS 140-3
validates *cryptographic modules*, not containers, applications, or images. A
container cannot be validated. What can be true is narrower: that an
application performs its cryptography exclusively through a validated module,
operating in its approved mode, on a host configured to enforce it.

Answering for this image therefore requires knowing which module performs each
cryptographic operation.

## Where cryptography happens in this image

| Operation | Performed by | Module |
| --- | --- | --- |
| Encrypting stored storage credentials | The Lakekeeper binary | A Rust crate compiled into the binary |
| Outbound TLS to object storage, identity providers, and PostgreSQL | The Lakekeeper binary | `rustls` and its cryptographic backend, compiled in |
| Inbound TLS | Nothing in this image. Lakekeeper does not terminate TLS | A reverse proxy outside the boundary |
| Package signature verification | `rpm` during build | Not part of the runtime |

The decisive fact is that **the upstream binary statically links its own
cryptography**. It links no OpenSSL: the measured library closure is `libc`,
`libm`, `libresolv`, `libgcc_s`, and the loader. Since the 2b change, the image
does not contain `openssl-libs` at all.

This matters because the usual Red Hat FIPS story does not apply. On RHEL, an
application that calls the system OpenSSL can inherit the validated Red Hat
cryptographic module and the system-wide FIPS policy. Lakekeeper does not call
system OpenSSL, so it inherits nothing. Running this image on a FIPS-enabled
RHEL host, with `fips=1` and a validated host module, **does not** place
Lakekeeper's cryptography inside a validated boundary. The host is in FIPS
mode; the application is not using the host's module.

Stating this plainly matters more than it might seem: "we run it on a FIPS
host" is the most common way organizations arrive at a FIPS claim they cannot
defend.

## What a real claim would require

- [ ] Identify the exact cryptographic crates and versions the locked
  Lakekeeper release compiles in, for both the secret-encryption path and the
  `rustls` backend. The current SBOM cannot answer this, because it resolves no
  crate inventory from the binary. That gap is Package 2c.
- [ ] Determine whether any of those crates have a FIPS 140-3 validated
  certificate, or whether a validated backend can be substituted. As of this
  analysis, the common Rust cryptographic backends are not validated modules in
  their default configurations, and a substitution would require building
  Lakekeeper from source against a different backend.
- [ ] If a source build against a validated module is required, evaluate the
  cost against Package 2c's source-build option, since both point the same way.
- [ ] Define the cryptographic boundary precisely: which operations are inside
  it, which are delegated to the proxy terminating TLS, which belong to
  PostgreSQL for data at rest, and which belong to the object store.
- [ ] Establish what the surrounding deployment must do, including the host
  FIPS policy, the TLS-terminating proxy's module, PostgreSQL's own
  cryptography, and key management for the secret encryption key.
- [ ] Decide whether "FIPS-capable deployment guidance" is worth publishing
  even when the application itself cannot be validated, and word it so that no
  reader can mistake it for a validation claim.

## Rules for anything this project publishes about FIPS

- Never write that the image "is FIPS compliant", "is FIPS validated", or "is
  FIPS certified". None of those are properties an image can have.
- Never present a UBI base as conferring FIPS status. UBI is a starting
  filesystem, not a cryptographic boundary, and this image does not use the
  system cryptographic libraries in any case.
- Never present "runs on a FIPS-enabled host" as a claim about this
  application. For this binary it is specifically not true.
- Never infer a claim from a passing SCAP profile. SCAP rules about FIPS check
  host and configuration state, not whether an application's linked
  cryptography is validated.
- If a partial statement is published, name the exact module, its certificate
  number, the approved mode, the operations covered, and the operations not
  covered.

## Current honest answer

This image's cryptography is performed by libraries compiled into an upstream
binary that this project does not build. Those libraries are not known to be
FIPS 140-3 validated modules, the image does not use the host's cryptographic
libraries, and no boundary has been defined or assessed. Any FIPS requirement
that an evaluator applies to this component is therefore **not met**, and
should be recorded as such rather than deferred or implied.
