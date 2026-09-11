# Third-party software and terms

The root [Apache License 2.0](LICENSE) applies to Datopsis-authored packaging
code and documentation in this repository. It does not replace the licenses or
terms of software assembled into the container image.

## Lakekeeper

The image installs the exact Lakekeeper release binary recorded in
`artifacts/lakekeeper.lock.json`. Lakekeeper is distributed by the Lakekeeper
project under the
[Apache License 2.0](https://github.com/lakekeeper/lakekeeper/blob/main/LICENSE).
Lakekeeper names and marks remain the property of their respective owners. This
independent packaging project is not affiliated with or endorsed by the
Lakekeeper project.

The shipped binary is a compiled Rust artifact that statically includes its
crate dependency tree. Those crates carry their own licenses, which are not
reproduced in this file. Release SBOMs must identify the dependency inventory
and licenses that the scanner can resolve from the binary, and the release
license review must cover them.

## Apache Iceberg

Lakekeeper implements the Apache Iceberg REST Catalog specification. Apache
Iceberg and Apache are trademarks of the Apache Software Foundation. This
project is not affiliated with or endorsed by the Apache Software Foundation.

## Red Hat Universal Base Image

The base image and installed runtime RPMs come from Red Hat UBI images and UBI
repositories. UBI content is redistributable subject to the
[Red Hat UBI terms and component licenses](https://developers.redhat.com/articles/ubi-faq).
Red Hat support is not included with this community image; eligibility depends
on the applicable subscription and supported deployment combination.

The image retains installed component license material. The OCI license
expression describes the principal packaging and Lakekeeper license
relationship; consumers must also review the SBOM, embedded notices, UBI terms,
and every component's license.

## PostgreSQL

PostgreSQL is a required external dependency and is not included in this image.
The development `compose.yaml` references an upstream PostgreSQL container image
for testing only; that image is not redistributed by this project and retains
its own license and terms.

## Release review

Before publishing a release:

1. Confirm all Red Hat packages came from approved UBI repositories and remain
   redistributable.
2. Confirm the Lakekeeper release source, license, and recorded digests match
   the artifact lock.
3. Inspect the SBOM for new packages, unknown licenses, and missing notices,
   including the Rust dependency inventory.
4. Retain upstream copyright, license, attribution, and trademark notices.
5. Update this file when package sources, image contents, branding, or
   distribution channels change.

This notice is operational documentation, not legal advice.
