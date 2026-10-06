#!/usr/bin/env python3

import csv
import re
from collections import defaultdict, Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

GOLDEN_FILE = BASE / "working/golden/golden_products.csv"
SOURCE_FILE = BASE / "working/golden/source_links.csv"
REVIEW_FILE = BASE / "working/golden/review_links.csv"

RESOLUTION_FILE = (
    BASE / "config/sku_collision_resolutions.csv"
)

OUTPUT_DIR = BASE / "working/golden/resolved"


def load(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def unique_split(values, separator):
    result = []

    for value in values:
        for item in (value or "").split(separator):
            item = item.strip()

            if item and item not in result:
                result.append(item)

    return result


def norm_sku(value):
    return re.sub(
        r"\s+",
        "",
        (value or "").strip().lower()
    )


golden = load(GOLDEN_FILE)
source_links = load(SOURCE_FILE)
review_links = load(REVIEW_FILE)
resolutions = load(RESOLUTION_FILE)

rows = {
    row["golden_id"]: row
    for row in golden
}

parent = {
    golden_id: golden_id
    for golden_id in rows
}


def find(value):
    while parent[value] != value:
        parent[value] = parent[parent[value]]
        value = parent[value]

    return value


def union(target, merged):
    rt = find(target)
    rm = find(merged)

    if rt == rm:
        return

    parent[rm] = rt


#
# Validate and apply explicit decisions.
#
for resolution in resolutions:

    target = resolution["target_golden_id"]
    merged = resolution["merge_golden_id"]

    if target not in rows:
        raise RuntimeError(
            f"Unknown target: {target}"
        )

    if merged not in rows:
        raise RuntimeError(
            f"Unknown merge record: {merged}"
        )

    if (
        norm_sku(rows[target]["canonical_sku"])
        != norm_sku(rows[merged]["canonical_sku"])
    ):
        raise RuntimeError(
            "Resolution SKU mismatch: "
            f"{target} / {merged}"
        )

    union(target, merged)


clusters = defaultdict(list)

for golden_id, row in rows.items():
    clusters[find(golden_id)].append(row)


#
# Original -> resolved ID map.
#
remap = {}

for root, members in clusters.items():
    for row in members:
        remap[row["golden_id"]] = root


#
# Remap source links.
#
resolved_source_links = []

for row in source_links:
    new = dict(row)
    new["golden_id"] = remap[
        row["golden_id"]
    ]
    resolved_source_links.append(new)


source_by_golden = defaultdict(list)

for row in resolved_source_links:
    source_by_golden[
        row["golden_id"]
    ].append(row)


#
# Remap remaining review links.
#
resolved_review_links = []
seen_reviews = set()

for row in review_links:

    new = dict(row)

    left = remap.get(
        row["identbase_golden_id"],
        row["identbase_golden_id"]
    )

    right = remap.get(
        row["interaktiv_golden_id"],
        row["interaktiv_golden_id"]
    )

    #
    # This review has just been resolved
    # by the explicit merge.
    #
    if left == right:
        continue

    new["identbase_golden_id"] = left
    new["interaktiv_golden_id"] = right

    key = (
        left,
        right,
        new["classification"],
    )

    if key in seen_reviews:
        continue

    seen_reviews.add(key)
    resolved_review_links.append(new)


review_count = Counter()

for row in resolved_review_links:
    review_count[
        row["identbase_golden_id"]
    ] += 1

    review_count[
        row["interaktiv_golden_id"]
    ] += 1


#
# Merge Golden rows.
#
resolved = []

for root, members in clusters.items():

    #
    # Root is always the explicitly selected
    # target for merged clusters.
    #
    base = dict(rows[root])

    idb_rows = [
        row
        for row in members
        if row["identbase_sku"].strip()
    ]

    if len(idb_rows) > 1:
        raise RuntimeError(
            f"Multiple Identbase records "
            f"in cluster {root}"
        )

    has_idb = bool(idb_rows)

    interaktiv_ids = unique_split(
        [
            row["interaktiv_group_id"]
            for row in members
        ],
        " | "
    )

    if has_idb and interaktiv_ids:
        base["record_type"] = (
            "IDENTBASE_MATCHED"
        )

    elif has_idb:
        base["record_type"] = (
            "IDENTBASE_ONLY"
        )

    else:
        base["record_type"] = (
            "INTERAKTIV_ONLY"
        )

    #
    # Keep every legacy value.
    #
    for field in (
        "legacy_skus",
        "legacy_eans",
        "legacy_manufacturers",
        "legacy_images",
        "legacy_prices",
    ):
        base[field] = " | ".join(
            unique_split(
                [
                    row[field]
                    for row in members
                ],
                " | "
            )
        )

    for field in (
        "legacy_names",
        "categories_legacy",
    ):
        base[field] = " || ".join(
            unique_split(
                [
                    row[field]
                    for row in members
                ],
                " || "
            )
        )

    #
    # Preserve all Interaktiv group IDs.
    #
    base["interaktiv_group_ids"] = (
        " | ".join(interaktiv_ids)
    )

    if interaktiv_ids:
        base["interaktiv_group_id"] = (
            interaktiv_ids[0]
        )
    else:
        base["interaktiv_group_id"] = ""

    #
    # Identbase remains authoritative.
    #
    if has_idb:
        idb = idb_rows[0]

        for field in (
            "canonical_sku",
            "identbase_sku",
            "identbase_mpn",
            "price",
            "special_price",
            "special_price_from",
            "special_price_to",
            "special_price_active",
            "effective_price",
            "price_source",
            "price_status",
            "product_type",
            "product_online",
            "visibility",
            "qty",
            "is_in_stock",
            "categories_identbase",
            "url_key",
            "meta_title",
            "meta_description",
        ):
            base[field] = idb[field]

    #
    # Recalculate lineage.
    #
    links = source_by_golden[root]

    base["source_count"] = str(
        len(links)
    )

    base["source_keys"] = (
        " | ".join(
            row["source_key"]
            for row in links
        )
    )

    count = review_count[root]

    base["review_candidate_count"] = str(
        count
    )

    flags = [
        value
        for value in unique_split(
            [
                row["review_flags"]
                for row in members
            ],
            " | "
        )
        if value not in {
            "REVIEW_POSSIBLE_MATCH",
            "REVIEW_NO_IDENTBASE_PRICE",
        }
    ]

    if not has_idb:
        flags.append(
            "REVIEW_NO_IDENTBASE_PRICE"
        )

    if count:
        flags.append(
            "REVIEW_POSSIBLE_MATCH"
        )

    base["review_flags"] = (
        " | ".join(
            dict.fromkeys(flags)
        )
    )

    resolved.append(base)


#
# Generate import_sku.
#
sku_groups = defaultdict(list)

for row in resolved:
    sku_groups[
        norm_sku(
            row["canonical_sku"]
        )
    ].append(row)


for sku, members in sku_groups.items():

    if len(members) == 1:
        members[0]["import_sku"] = (
            members[0]["canonical_sku"]
        )
        continue

    idb_members = [
        row
        for row in members
        if row["identbase_sku"]
    ]

    #
    # If Identbase participates, it keeps
    # its authoritative SKU.
    #
    if len(idb_members) == 1:

        idb = idb_members[0]

        idb["import_sku"] = (
            idb["canonical_sku"]
        )

        for row in members:
            if row is idb:
                continue

            row["import_sku"] = (
                "LEGACY-"
                + row["golden_id"]
                .replace("G-", "")
            )

    else:
        #
        # Pure legacy collision:
        # nobody gets arbitrary priority.
        #
        for row in members:
            row["import_sku"] = (
                "LEGACY-"
                + row["golden_id"]
                .replace("G-", "")
            )


#
# Final validation.
#
import_skus = [
    norm_sku(row["import_sku"])
    for row in resolved
]

if len(import_skus) != len(set(import_skus)):
    raise RuntimeError(
        "Duplicate import_sku remains"
    )


expected = (
    len(golden)
    - len(resolutions)
)

if len(resolved) != expected:
    raise RuntimeError(
        f"Unexpected resolved count: "
        f"{len(resolved)} != {expected}"
    )


OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


#
# Golden products.
#
fields = list(resolved[0].keys())

for new_field in (
    "interaktiv_group_ids",
    "import_sku",
):
    if new_field not in fields:
        fields.append(new_field)


with (
    OUTPUT_DIR / "golden_products.csv"
).open(
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
    writer.writerows(resolved)


#
# Source links.
#
with (
    OUTPUT_DIR / "source_links.csv"
).open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    fields_source = list(
        resolved_source_links[0].keys()
    )

    writer = csv.DictWriter(
        f,
        fieldnames=fields_source
    )

    writer.writeheader()
    writer.writerows(
        resolved_source_links
    )


#
# Review links.
#
if resolved_review_links:

    with (
        OUTPUT_DIR / "review_links.csv"
    ).open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        fields_review = list(
            resolved_review_links[0].keys()
        )

        writer = csv.DictWriter(
            f,
            fieldnames=fields_review
        )

        writer.writeheader()
        writer.writerows(
            resolved_review_links
        )


#
# ID remap.
#
with (
    OUTPUT_DIR / "golden_id_remap.csv"
).open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.writer(f)

    writer.writerow([
        "old_golden_id",
        "resolved_golden_id",
    ])

    for old_id in sorted(remap):
        writer.writerow([
            old_id,
            remap[old_id],
        ])


remaining_collisions = {
    sku: members
    for sku, members in sku_groups.items()
    if len(members) > 1
}

technical_skus = sum(
    1
    for row in resolved
    if row["import_sku"].startswith(
        "LEGACY-"
    )
)


print()
print(
    "===== COLLISION RESOLUTION ====="
)

print(
    f"Golden before:              "
    f"{len(golden)}"
)

print(
    f"Applied merge operations:   "
    f"{len(resolutions)}"
)

print(
    f"Golden after:               "
    f"{len(resolved)}"
)

print()

print(
    f"Remaining canonical SKU "
    f"collisions:                 "
    f"{len(remaining_collisions)}"
)

print(
    f"Technical import SKUs:      "
    f"{technical_skus}"
)

print()

print(
    f"Source links:               "
    f"{len(resolved_source_links)}"
)

print(
    f"Remaining review links:     "
    f"{len(resolved_review_links)}"
)

print()
print("Output:")
print(OUTPUT_DIR)
