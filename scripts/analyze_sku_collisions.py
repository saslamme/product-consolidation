#!/usr/bin/env python3

import csv
import re
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

GOLDEN_FILE = (
    BASE
    / "working"
    / "golden"
    / "golden_products.csv"
)

OUTPUT_FILE = (
    BASE
    / "working"
    / "golden"
    / "validation"
    / "sku_collision_analysis.csv"
)


def norm_sku(value):
    return re.sub(
        r"\s+",
        "",
        (value or "").strip().lower()
    )


def norm_name(value):
    value = (value or "").strip().lower()

    value = re.sub(
        r"[^a-z0-9äöüß]+",
        " ",
        value
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def similarity(a, b):
    a = norm_name(a)
    b = norm_name(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


with GOLDEN_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    rows = list(csv.DictReader(f))


groups = defaultdict(list)

for row in rows:
    sku = norm_sku(
        row["canonical_sku"]
    )

    if sku:
        groups[sku].append(row)


collisions = {
    sku: records
    for sku, records in groups.items()
    if len(records) > 1
}


output = []
type_counts = Counter()


for sku, records in sorted(
    collisions.items()
):

    types = {
        r["record_type"]
        for r in records
    }

    idb_count = sum(
        1
        for r in records
        if r["identbase_sku"]
    )

    int_only_count = sum(
        1
        for r in records
        if r["record_type"]
        == "INTERAKTIV_ONLY"
    )

    if idb_count > 1:
        collision_type = (
            "IDENTBASE_SKU_COLLISION"
        )

    elif (
        idb_count == 1
        and int_only_count >= 1
    ):
        collision_type = (
            "IDENTBASE_VS_LEGACY"
        )

    elif (
        idb_count == 0
        and int_only_count > 1
    ):
        collision_type = (
            "LEGACY_VS_LEGACY"
        )

    else:
        collision_type = (
            "OTHER"
        )

    type_counts[
        collision_type
    ] += 1

    #
    # Pairwise name similarity.
    #
    similarities = []

    for i in range(len(records)):
        for j in range(
            i + 1,
            len(records)
        ):
            similarities.append(
                similarity(
                    records[i]["name_de"],
                    records[j]["name_de"]
                )
            )

    max_similarity = (
        max(similarities)
        if similarities
        else 0
    )

    min_similarity = (
        min(similarities)
        if similarities
        else 0
    )

    for row in records:

        output.append({
            "normalized_sku": sku,
            "collision_type": (
                collision_type
            ),
            "records_in_collision": (
                len(records)
            ),
            "min_name_similarity": (
                round(
                    min_similarity,
                    4
                )
            ),
            "max_name_similarity": (
                round(
                    max_similarity,
                    4
                )
            ),

            "golden_id": (
                row["golden_id"]
            ),

            "record_type": (
                row["record_type"]
            ),

            "canonical_sku": (
                row["canonical_sku"]
            ),

            "identbase_sku": (
                row["identbase_sku"]
            ),

            "identbase_mpn": (
                row["identbase_mpn"]
            ),

            "interaktiv_group_id": (
                row[
                    "interaktiv_group_id"
                ]
            ),

            "name_de": (
                row["name_de"]
            ),

            "manufacturer": (
                row["manufacturer"]
            ),

            "ean": (
                row["ean"]
            ),

            "legacy_skus": (
                row["legacy_skus"]
            ),

            "legacy_eans": (
                row["legacy_eans"]
            ),

            "source_keys": (
                row["source_keys"]
            ),

            "review_flags": (
                row["review_flags"]
            ),
        })


fields = list(
    output[0].keys()
)

with OUTPUT_FILE.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(output)


print()
print(
    "===== SKU COLLISION ANALYSIS ====="
)

print(
    f"Kollidierende SKU-Werte: "
    f"{len(collisions)}"
)

print(
    f"Betroffene Golden Records: "
    f"{len(output)}"
)

print()

for name, count in sorted(
    type_counts.items()
):
    print(
        f"{name:30} {count}"
    )

print()
print("===== DETAILS =====")

for sku, records in sorted(
    collisions.items()
):

    print()
    print("=" * 100)
    print(
        f"SKU: {sku} "
        f"({len(records)} Records)"
    )

    for row in records:
        print()
        print(
            row["record_type"],
            "|",
            row["golden_id"]
        )

        print(
            "Canonical:",
            row["canonical_sku"]
        )

        print(
            "Identbase:",
            row["identbase_sku"]
            or "-"
        )

        print(
            "MPN:",
            row["identbase_mpn"]
            or "-"
        )

        print(
            "Legacy:",
            row["legacy_skus"]
            or "-"
        )

        print(
            "Name:",
            row["name_de"]
        )

        print(
            "Hersteller:",
            row["manufacturer"]
            or "-"
        )

        print(
            "EAN:",
            row["ean"]
            or "-"
        )

        print(
            "Flags:",
            row["review_flags"]
            or "-"
        )

print()
print("Output:")
print(OUTPUT_FILE)
