#!/usr/bin/env python3
"""Write and read real table rows through a query engine.

The rest of the suite talks to the catalog's HTTP API directly, which proves
the catalog agrees with itself. This uses PyIceberg, an independent
implementation of the Iceberg specification, so a disagreement between the
catalog and the specification shows up as a failure here rather than as a
surprise for the first engine an operator points at it.

The round trip crosses both stores on purpose. Table rows become Parquet files
in object storage, while the commit that makes them visible is a catalog
operation recorded in PostgreSQL. Reading the rows back afterwards therefore
depends on both, and on them agreeing.
"""

from __future__ import annotations

import os
import sys

import pyarrow
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError

NAMESPACE = "roundtrip"
TABLE = "readings"

ROWS = {
    "id": [1, 2, 3],
    "label": ["alpha", "beta", "gamma"],
    "value": [1.5, 2.5, 3.5],
}


def build_catalog() -> RestCatalog:
    return RestCatalog(
        "qualification",
        **{
            "uri": os.environ["CATALOG_URI"],
            "warehouse": os.environ["WAREHOUSE"],
            # This profile keeps credentials server-side rather than vending
            # them, so the engine brings its own. That is the trust model being
            # qualified; see docs/ROADMAP.md.
            "s3.endpoint": os.environ["S3_ENDPOINT"],
            "s3.access-key-id": os.environ["S3_ACCESS_KEY_ID"],
            "s3.secret-access-key": os.environ["S3_SECRET_ACCESS_KEY"],
            "s3.region": "local",
            "s3.path-style-access": "true",
        },
    )


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "write"
    catalog = build_catalog()
    expected = pyarrow.table(ROWS)

    if mode == "write":
        try:
            catalog.create_namespace(NAMESPACE)
        except NamespaceAlreadyExistsError:
            pass

        table = catalog.create_table(f"{NAMESPACE}.{TABLE}", schema=expected.schema)
        table.append(expected)
        print(f"metadata-location={table.metadata_location}")

    table = catalog.load_table(f"{NAMESPACE}.{TABLE}")
    actual = table.scan().to_arrow()

    if actual.num_rows != expected.num_rows:
        print(
            f"row count mismatch: wrote {expected.num_rows}, read {actual.num_rows}",
            file=sys.stderr,
        )
        return 1

    actual_sorted = actual.sort_by("id").select(["id", "label", "value"])
    expected_sorted = expected.sort_by("id").select(["id", "label", "value"])
    if actual_sorted.to_pydict() != expected_sorted.to_pydict():
        print("row content mismatch", file=sys.stderr)
        print(f"  wrote: {expected_sorted.to_pydict()}", file=sys.stderr)
        print(f"  read:  {actual_sorted.to_pydict()}", file=sys.stderr)
        return 1

    # A data file list proves the rows are in object storage rather than only
    # in a catalog response.
    data_files = [
        task.file.file_path for task in table.scan().plan_files()
    ]
    if not data_files:
        print("the table reports no data files", file=sys.stderr)
        return 1
    for path in data_files:
        print(f"data-file={path}")

    print(f"{mode}: {actual.num_rows} rows round-tripped through PyIceberg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
