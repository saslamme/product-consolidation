#!/usr/bin/env python3

import csv
import re
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

SAFE_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "safe_matches.csv"
)

REVIEW_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "review_matches.csv"
)

PROMOTION_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "promotion_candidates.csv"
)

OUTPUT_DIR = (
    BASE
    / "working"
    / "identbase_matching"
    / "final"
)


def norm_identifier(value):
    return re.sub(
        r"\s+",
        "",
        (value or "").strip().lower()
    )


def numeric_identifier(value):
    value = norm_identifier(value)

    if not value.isdigit():
        return ""

    value = value.lstrip("0")

    return value or "0"


def split_legacy_skus(value):
    return [
        item.strip()
        for item in (value or "").split("|")
        if item.strip()
    ]


def numeric_matches(value, legacy_skus):
    left = numeric_identifier(value)

    if not left:
        return False

    for sku in legacy_skus:
        right = numeric_identifier(sku)

        if right and left == right:
            return True

    return False


def write_csv(path, rows, fieldnames):
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
            fieldnames=fieldnames,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


#
# Existing SAFE matches
#
with SAFE_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    existing_safe = list(
        csv.DictReader(f)
    )


#
# Original review matches
#
with REVIEW_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    reviews = list(
        csv.DictReader(f)
    )


#
# Promotion analysis with manufacturer state
#
with PROMOTION_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    promotion_rows = list(
        csv.DictReader(f)
    )


promotion_lookup = {
    (
        row["identbase_sku"],
        row["interaktiv_group_id"],
    ): row
    for row in promotion_rows
}


promoted = []
remaining_review = []


for row in reviews:

    key = (
        row["identbase_sku"],
        row["interaktiv_group_id"],
    )

    promo = promotion_lookup.get(key)

    if promo is None:
        remaining_review.append(row)
        continue

    legacy_skus = split_legacy_skus(
        row["interaktiv_skus"]
    )

    mpn = (
        row["identbase_mpn"]
        or ""
    ).strip()

    sku = (
        row["identbase_sku"]
        or ""
    ).strip()

    similarity = float(
        row["name_similarity"]
        or 0
    )

    idb_candidates = int(
        row["identbase_candidate_groups"]
        or 0
    )

    legacy_candidates = int(
        row["group_candidate_identbase"]
        or 0
    )

    manufacturer_state = (
        promo["manufacturer_state"]
    )

    method = ""
    confidence = 0

    #
    # Rule A:
    # Pure numeric identifier differs only
    # by leading zero(s).
    #
    if (
        idb_candidates == 1
        and legacy_candidates == 1
        and similarity >= 0.90
        and manufacturer_state != "CONFLICT"
        and numeric_matches(
            sku,
            legacy_skus
        )
    ):
        method = "SAFE_SKU_NUMERIC_NORMALIZED"
        confidence = 100

    elif (
        idb_candidates == 1
        and legacy_candidates == 1
        and similarity >= 0.90
        and manufacturer_state != "CONFLICT"
        and numeric_matches(
            mpn,
            legacy_skus
        )
    ):
        method = "SAFE_MPN_NUMERIC_NORMALIZED"
        confidence = 99

    #
    # Rule B:
    # Name-only match may be promoted only
    # if there is NO Identbase MPN that
    # contradicts the legacy identifier.
    #
    elif (
        row["classification"]
        == "REVIEW_NAME"
        and similarity >= 0.9999
        and idb_candidates == 1
        and legacy_candidates == 1
        and manufacturer_state != "CONFLICT"
        and not mpn
    ):
        method = "SAFE_NAME_1TO1_NO_MPN"
        confidence = 96

    if method:

        promoted.append({
            **row,
            "classification": method,
            "confidence": confidence,
            "promotion_method": method,
            "manufacturer_state": (
                manufacturer_state
            ),
        })

    else:
        remaining_review.append(row)


#
# Make final SAFE list.
#
final_safe = []

for row in existing_safe:
    final_safe.append({
        **row,
        "promotion_method": "",
        "manufacturer_state": "",
    })

final_safe.extend(promoted)


#
# Safety check:
# No Identbase product or Interaktiv group
# may occur more than once in final SAFE.
#
idb_seen = {}
group_seen = {}

conflicts = []

for row in final_safe:

    sku = row["identbase_sku"]
    group = row["interaktiv_group_id"]

    if sku in idb_seen:
        conflicts.append(
            (
                "IDENTBASE_DUPLICATE",
                sku,
                group,
            )
        )

    if group in group_seen:
        conflicts.append(
            (
                "INTERAKTIV_DUPLICATE",
                sku,
                group,
            )
        )

    idb_seen[sku] = group
    group_seen[group] = sku


if conflicts:
    print()
    print("ERROR: Final SAFE conflicts found")

    for conflict in conflicts[:30]:
        print(conflict)

    raise SystemExit(1)


safe_fields = [
    "classification",
    "confidence",

    "identbase_sku",
    "identbase_mpn",
    "identbase_name",
    "identbase_manufacturer",
    "identbase_price",

    "interaktiv_group_id",
    "interaktiv_skus",
    "interaktiv_names",
    "interaktiv_manufacturers",

    "evidence",
    "name_similarity",
    "manufacturer_match",

    "identbase_candidate_groups",
    "group_candidate_identbase",

    "reason",

    "promotion_method",
    "manufacturer_state",
]


review_fields = list(
    reviews[0].keys()
)


write_csv(
    OUTPUT_DIR
    / "safe_matches.csv",
    final_safe,
    safe_fields,
)

write_csv(
    OUTPUT_DIR
    / "review_matches.csv",
    remaining_review,
    review_fields,
)

write_csv(
    OUTPUT_DIR
    / "promoted_matches.csv",
    promoted,
    safe_fields,
)


print()
print(
    "===== FINAL IDENTBASE MATCHING ====="
)

print(
    f"Original SAFE:             "
    f"{len(existing_safe)}"
)

print(
    f"Neu promoted:              "
    f"{len(promoted)}"
)

print(
    f"Final SAFE:                "
    f"{len(final_safe)}"
)

print(
    f"Verbleibende Review-Paare: "
    f"{len(remaining_review)}"
)

print()
print("Promotions:")

methods = {}

for row in promoted:
    method = row["promotion_method"]

    methods[method] = (
        methods.get(method, 0) + 1
    )

for method, count in sorted(
    methods.items()
):
    print(
        f"  {method:35} {count}"
    )

print()
print("Output:")
print(OUTPUT_DIR)
