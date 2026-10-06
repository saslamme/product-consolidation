#!/usr/bin/env python3

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

GOLDEN_FILE = (
    BASE
    / "working"
    / "golden"
    / "golden_products.csv"
)

SOURCE_FILE = (
    BASE
    / "working"
    / "golden"
    / "source_links.csv"
)

OUTPUT_DIR = (
    BASE
    / "working"
    / "golden"
    / "validation"
)


def load(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def norm_sku(value):
    value = (value or "").strip().lower()

    return re.sub(
        r"\s+",
        "",
        value
    )


def write_csv(path, rows, fields):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


golden = load(GOLDEN_FILE)
source_links = load(SOURCE_FILE)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# --------------------------------------------------
# Golden IDs
# --------------------------------------------------

golden_ids = [
    row["golden_id"]
    for row in golden
]

duplicate_golden_ids = [
    key
    for key, count in Counter(
        golden_ids
    ).items()
    if count > 1
]


# --------------------------------------------------
# Source keys
# --------------------------------------------------

source_keys = [
    row["source_key"]
    for row in source_links
]

duplicate_source_keys = [
    key
    for key, count in Counter(
        source_keys
    ).items()
    if count > 1
]


# --------------------------------------------------
# Canonical SKU collisions
# --------------------------------------------------

sku_groups = defaultdict(list)

for row in golden:

    sku = norm_sku(
        row["canonical_sku"]
    )

    if sku:
        sku_groups[sku].append(row)


duplicate_skus = []

for sku, rows in sku_groups.items():

    if len(rows) <= 1:
        continue

    for row in rows:
        duplicate_skus.append({
            "normalized_sku": sku,
            "count": len(rows),
            "golden_id": row["golden_id"],
            "record_type": row["record_type"],
            "canonical_sku": row["canonical_sku"],
            "identbase_sku": row["identbase_sku"],
            "interaktiv_group_id": row["interaktiv_group_id"],
            "name_de": row["name_de"],
            "manufacturer": row["manufacturer"],
            "review_flags": row["review_flags"],
        })


# --------------------------------------------------
# Missing important fields
# --------------------------------------------------

missing = []

for row in golden:

    if not row["canonical_sku"].strip():
        missing.append({
            "golden_id": row["golden_id"],
            "issue": "MISSING_CANONICAL_SKU",
            "record_type": row["record_type"],
            "name_de": row["name_de"],
        })

    if not row["name_de"].strip():
        missing.append({
            "golden_id": row["golden_id"],
            "issue": "MISSING_NAME_DE",
            "record_type": row["record_type"],
            "name_de": "",
        })


# --------------------------------------------------
# Price authority
# --------------------------------------------------

price_violations = []

for row in golden:

    if (
        row["record_type"]
        == "INTERAKTIV_ONLY"
        and row["effective_price"].strip()
    ):
        price_violations.append({
            "golden_id": row["golden_id"],
            "issue": "LEGACY_CANONICAL_PRICE",
            "effective_price": row["effective_price"],
            "price_source": row["price_source"],
        })

    if (
        row["price_source"]
        and row["price_source"] != "IDENTBASE"
    ):
        price_violations.append({
            "golden_id": row["golden_id"],
            "issue": "INVALID_PRICE_SOURCE",
            "effective_price": row["effective_price"],
            "price_source": row["price_source"],
        })


# --------------------------------------------------
# Record-type consistency
# --------------------------------------------------

type_violations = []

for row in golden:

    record_type = row["record_type"]

    has_idb = bool(
        row["identbase_sku"].strip()
    )

    has_int = bool(
        row[
            "interaktiv_group_id"
        ].strip()
    )

    valid = (
        (
            record_type
            == "IDENTBASE_MATCHED"
            and has_idb
            and has_int
        )
        or (
            record_type
            == "IDENTBASE_ONLY"
            and has_idb
            and not has_int
        )
        or (
            record_type
            == "INTERAKTIV_ONLY"
            and not has_idb
            and has_int
        )
    )

    if not valid:
        type_violations.append({
            "golden_id": row["golden_id"],
            "record_type": record_type,
            "identbase_sku": row["identbase_sku"],
            "interaktiv_group_id": row[
                "interaktiv_group_id"
            ],
        })


# --------------------------------------------------
# Reports
# --------------------------------------------------

write_csv(
    OUTPUT_DIR / "duplicate_skus.csv",
    duplicate_skus,
    [
        "normalized_sku",
        "count",
        "golden_id",
        "record_type",
        "canonical_sku",
        "identbase_sku",
        "interaktiv_group_id",
        "name_de",
        "manufacturer",
        "review_flags",
    ],
)

write_csv(
    OUTPUT_DIR / "missing_fields.csv",
    missing,
    [
        "golden_id",
        "issue",
        "record_type",
        "name_de",
    ],
)

write_csv(
    OUTPUT_DIR / "price_violations.csv",
    price_violations,
    [
        "golden_id",
        "issue",
        "effective_price",
        "price_source",
    ],
)

write_csv(
    OUTPUT_DIR / "record_type_violations.csv",
    type_violations,
    [
        "golden_id",
        "record_type",
        "identbase_sku",
        "interaktiv_group_id",
    ],
)


record_counts = Counter(
    row["record_type"]
    for row in golden
)

review_flagged = sum(
    1
    for row in golden
    if "REVIEW_POSSIBLE_MATCH"
    in row["review_flags"]
)

price_counts = Counter(
    row["price_status"]
    for row in golden
)


print()
print("===== GOLDEN VALIDATION =====")

print()
print("Records:")
print(
    f"  Golden products:       "
    f"{len(golden)}"
)
print(
    f"  Source links:          "
    f"{len(source_links)}"
)

print()
print("Record types:")

for key in (
    "IDENTBASE_MATCHED",
    "IDENTBASE_ONLY",
    "INTERAKTIV_ONLY",
):
    print(
        f"  {key:24}"
        f"{record_counts[key]}"
    )

print()
print("Integrity:")
print(
    f"  Duplicate golden IDs:  "
    f"{len(duplicate_golden_ids)}"
)
print(
    f"  Duplicate source keys: "
    f"{len(duplicate_source_keys)}"
)
print(
    f"  Duplicate SKUs:        "
    f"{len(sku_groups) - sum(1 for v in sku_groups.values() if len(v) == 1)}"
)
print(
    f"  Missing fields:        "
    f"{len(missing)}"
)
print(
    f"  Type violations:       "
    f"{len(type_violations)}"
)
print(
    f"  Price violations:      "
    f"{len(price_violations)}"
)

print()
print("Price status:")

for key, value in sorted(
    price_counts.items()
):
    print(
        f"  {key:35}"
        f"{value}"
    )

print()
print(
    f"Records with review candidate: "
    f"{review_flagged}"
)

print()
print("Reports:")
print(OUTPUT_DIR)


#
# Hard failures.
#
if (
    duplicate_golden_ids
    or duplicate_source_keys
    or type_violations
    or price_violations
):
    raise SystemExit(1)
