#!/usr/bin/env python3

import csv
import hashlib
import re
from collections import defaultdict, Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

IDB_FILE = (
    BASE
    / "working"
    / "identbase"
    / "products.csv"
)

INT_MASTER_FILE = (
    BASE
    / "working"
    / "interaktiv"
    / "merged"
    / "interaktiv_master_products.csv"
)

INT_PRODUCT_DIR = (
    BASE
    / "working"
    / "interaktiv"
    / "products"
)

SAFE_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "final"
    / "safe_matches.csv"
)

REVIEW_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "final"
    / "review_matches.csv"
)

OUTPUT_DIR = (
    BASE
    / "working"
    / "golden"
)

SHOPS = (
    "identible",
    "cardnext",
    "inplastor",
)

SOURCE_PRIORITY = {
    "identible": 1,
    "cardnext": 2,
    "inplastor": 3,
}


def clean(value):
    return (value or "").strip()


def stable_id(prefix, value):
    digest = hashlib.sha1(
        value.encode("utf-8")
    ).hexdigest()[:12].upper()

    return f"G-{prefix}-{digest}"


def unique_values(values):
    result = []

    for value in values:
        value = clean(value)

        if value and value not in result:
            result.append(value)

    return result


def legacy_description(row):
    description = clean(
        row.get("description", "")
    )

    if description:
        return description

    #
    # Inplastor uses field 25 for some
    # historical descriptions.
    #
    alternative = clean(
        row.get("raw_25", "")
    )

    if (
        len(alternative) >= 30
        and not alternative.isdigit()
    ):
        return alternative

    return ""


def best_legacy_description(records):
    values = []

    for row in records:
        value = legacy_description(row)

        if value:
            values.append(value)

    if not values:
        return ""

    return max(
        values,
        key=len
    )


def first_legacy_value(
    records,
    field
):
    ordered = sorted(
        records,
        key=lambda row: (
            SOURCE_PRIORITY[
                row["source"]
            ],
            row.get("master_id", ""),
        )
    )

    for row in ordered:
        value = clean(
            row.get(field, "")
        )

        if value:
            return value

    return ""


def load_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(
            csv.DictReader(f)
        )


#
# --------------------------------------------------
# Load Identbase
# --------------------------------------------------
#

identbase_rows = load_csv(
    IDB_FILE
)

identbase = {
    row["sku"]: row
    for row in identbase_rows
}


#
# --------------------------------------------------
# Load Interaktiv groups
# --------------------------------------------------
#

interaktiv_rows = load_csv(
    INT_MASTER_FILE
)

interaktiv = {
    row["interaktiv_group_id"]: row
    for row in interaktiv_rows
}


#
# --------------------------------------------------
# Load original per-shop Interaktiv products
# --------------------------------------------------
#

legacy_products = {}

for shop in SHOPS:

    path = (
        INT_PRODUCT_DIR
        / f"{shop}.csv"
    )

    for row in load_csv(path):

        row["source"] = shop

        key = (
            shop,
            row["master_id"],
        )

        legacy_products[key] = row


#
# --------------------------------------------------
# Load final SAFE matches
# --------------------------------------------------
#

safe_rows = load_csv(
    SAFE_FILE
)

safe_by_idb = {}
safe_by_group = {}

for row in safe_rows:

    idb_sku = row["identbase_sku"]
    group_id = row[
        "interaktiv_group_id"
    ]

    if idb_sku in safe_by_idb:
        raise RuntimeError(
            f"Duplicate SAFE Identbase SKU: "
            f"{idb_sku}"
        )

    if group_id in safe_by_group:
        raise RuntimeError(
            f"Duplicate SAFE Interaktiv group: "
            f"{group_id}"
        )

    safe_by_idb[idb_sku] = row
    safe_by_group[group_id] = row


#
# --------------------------------------------------
# Load remaining review candidates
# --------------------------------------------------
#

review_rows = load_csv(
    REVIEW_FILE
)

review_by_idb = defaultdict(list)
review_by_group = defaultdict(list)

for row in review_rows:

    review_by_idb[
        row["identbase_sku"]
    ].append(row)

    review_by_group[
        row["interaktiv_group_id"]
    ].append(row)


#
# --------------------------------------------------
# Resolve underlying legacy records
# --------------------------------------------------
#

def records_for_group(group):
    records = []

    for shop in SHOPS:

        master_id = clean(
            group.get(
                f"{shop}_master_id",
                ""
            )
        )

        if not master_id:
            continue

        key = (
            shop,
            master_id,
        )

        row = legacy_products.get(key)

        if row is None:
            raise RuntimeError(
                "Legacy source product missing: "
                f"{shop}:{master_id}"
            )

        records.append(row)

    return records


#
# --------------------------------------------------
# Golden row builder
# --------------------------------------------------
#

def build_golden(
    idb=None,
    group=None,
    match=None,
):
    if idb is not None:

        golden_id = stable_id(
            "IDB",
            "identbase:"
            + idb["sku"]
        )

    else:

        golden_id = stable_id(
            "INT",
            "interaktiv:"
            + group[
                "interaktiv_group_id"
            ]
        )

    legacy = (
        records_for_group(group)
        if group is not None
        else []
    )

    legacy_skus = unique_values(
        row.get("sku", "")
        for row in legacy
    )

    legacy_eans = unique_values(
        row.get("ean", "")
        for row in legacy
    )

    legacy_manufacturers = (
        unique_values(
            row.get(
                "manufacturer",
                ""
            )
            for row in legacy
        )
    )

    legacy_names = unique_values(
        row.get("name", "")
        for row in legacy
    )

    legacy_images = unique_values(
        row.get("image", "")
        for row in legacy
    )

    legacy_prices = unique_values(
        row.get("price", "")
        for row in legacy
    )

    #
    # EAN is retained from legacy, but
    # never treated as Identbase-authoritative.
    #
    ean = ""

    if len(legacy_eans) == 1:
        ean = legacy_eans[0]

    #
    # Canonical textual data:
    # Identbase first, legacy fallback.
    #
    name_de = (
        clean(idb["name_de"])
        if idb is not None
        else ""
    )

    if not name_de:
        name_de = first_legacy_value(
            legacy,
            "name"
        )

    manufacturer = (
        clean(idb["manufacturer"])
        if idb is not None
        else ""
    )

    if not manufacturer:
        manufacturer = (
            first_legacy_value(
                legacy,
                "manufacturer"
            )
        )

    description_de = (
        clean(
            idb["description_de"]
        )
        if idb is not None
        else ""
    )

    if not description_de:
        description_de = (
            best_legacy_description(
                legacy
            )
        )

    short_description_de = (
        clean(
            idb[
                "short_description_de"
            ]
        )
        if idb is not None
        else ""
    )

    base_image = (
        clean(idb["base_image"])
        if idb is not None
        else ""
    )

    if not base_image:
        base_image = (
            first_legacy_value(
                legacy,
                "image"
            )
        )

    #
    # IMPORTANT:
    # Canonical price ONLY from Identbase.
    #
    price = ""
    special_price = ""
    effective_price = ""
    price_source = ""
    price_status = ""

    if idb is not None:

        price = clean(
            idb["price"]
        )

        special_price = clean(
            idb["special_price"]
        )

        effective_price = clean(
            idb["effective_price"]
        )

        if effective_price:
            price_source = "IDENTBASE"
            price_status = "OK"
        else:
            price_source = ""
            price_status = (
                "REVIEW_IDENTBASE_PRICE_MISSING"
            )

    else:

        price_status = (
            "REVIEW_NO_IDENTBASE_PRICE"
        )

    #
    # Record type
    #
    if (
        idb is not None
        and group is not None
    ):
        record_type = (
            "IDENTBASE_MATCHED"
        )

    elif idb is not None:
        record_type = (
            "IDENTBASE_ONLY"
        )

    else:
        record_type = (
            "INTERAKTIV_ONLY"
        )

    #
    # Review flags only for currently
    # unmatched records.
    #
    review_candidates = []

    if (
        idb is not None
        and group is None
    ):
        review_candidates = (
            review_by_idb.get(
                idb["sku"],
                []
            )
        )

    elif (
        idb is None
        and group is not None
    ):
        review_candidates = (
            review_by_group.get(
                group[
                    "interaktiv_group_id"
                ],
                []
            )
        )

    flags = []

    if price_status != "OK":
        flags.append(
            price_status
        )

    if review_candidates:
        flags.append(
            "REVIEW_POSSIBLE_MATCH"
        )

    if len(legacy_eans) > 1:
        flags.append(
            "REVIEW_EAN_CONFLICT"
        )

    #
    # Source keys
    #
    source_keys = []

    if idb is not None:
        source_keys.append(
            "identbase:"
            + idb["sku"]
        )

    for row in legacy:
        source_keys.append(
            f"{row['source']}:"
            f"{row['master_id']}"
        )

    canonical_sku = (
        idb["sku"]
        if idb is not None
        else (
            clean(
                group[
                    "reference_sku"
                ]
            )
            if group is not None
            else ""
        )
    )

    #
    # Legacy categories.
    # Identbase-only records have no
    # Interaktiv group.
    #
    legacy_categories = []

    if group is not None:
        for shop in SHOPS:
            value = clean(
                group.get(
                    f"{shop}_categories",
                    ""
                )
            )

            if not value:
                continue

            for category in value.split(" || "):
                category = clean(category)

                if (
                    category
                    and category
                    not in legacy_categories
                ):
                    legacy_categories.append(
                        category
                    )

    legacy_categories_value = (
        " || ".join(
            legacy_categories
        )
    )

    return {
        "golden_id": golden_id,
        "record_type": record_type,

        "canonical_sku": (
            canonical_sku
        ),

        "identbase_sku": (
            idb["sku"]
            if idb is not None
            else ""
        ),

        "identbase_mpn": (
            idb["mpn"]
            if idb is not None
            else ""
        ),

        "interaktiv_group_id": (
            group[
                "interaktiv_group_id"
            ]
            if group is not None
            else ""
        ),

        "match_classification": (
            match["classification"]
            if match is not None
            else ""
        ),

        "match_confidence": (
            match["confidence"]
            if match is not None
            else ""
        ),

        "name_de": name_de,

        "name_en": (
            idb["name_en"]
            if idb is not None
            else ""
        ),

        "name_fr": (
            idb["name_fr"]
            if idb is not None
            else ""
        ),

        "name_es": (
            idb["name_es"]
            if idb is not None
            else ""
        ),

        "description_de": (
            description_de
        ),

        "description_en": (
            idb["description_en"]
            if idb is not None
            else ""
        ),

        "description_fr": (
            idb["description_fr"]
            if idb is not None
            else ""
        ),

        "description_es": (
            idb["description_es"]
            if idb is not None
            else ""
        ),

        "short_description_de": (
            short_description_de
        ),

        "short_description_en": (
            idb[
                "short_description_en"
            ]
            if idb is not None
            else ""
        ),

        "short_description_fr": (
            idb[
                "short_description_fr"
            ]
            if idb is not None
            else ""
        ),

        "short_description_es": (
            idb[
                "short_description_es"
            ]
            if idb is not None
            else ""
        ),

        "manufacturer": (
            manufacturer
        ),

        "ean": ean,

        "ean_source": (
            "LEGACY_UNVERIFIED"
            if ean
            else ""
        ),

        "price": price,

        "special_price": (
            special_price
        ),

        "special_price_from": (
            idb[
                "special_price_from"
            ]
            if idb is not None
            else ""
        ),

        "special_price_to": (
            idb[
                "special_price_to"
            ]
            if idb is not None
            else ""
        ),

        "special_price_active": (
            idb[
                "special_price_active"
            ]
            if idb is not None
            else ""
        ),

        "effective_price": (
            effective_price
        ),

        "price_source": (
            price_source
        ),

        "price_status": (
            price_status
        ),

        "product_type": (
            idb["product_type"]
            if idb is not None
            else ""
        ),

        "product_online": (
            idb["product_online"]
            if idb is not None
            else ""
        ),

        "visibility": (
            idb["visibility"]
            if idb is not None
            else ""
        ),

        "qty": (
            idb["qty"]
            if idb is not None
            else ""
        ),

        "is_in_stock": (
            idb["is_in_stock"]
            if idb is not None
            else ""
        ),

        "categories_identbase": (
            idb["categories"]
            if idb is not None
            else ""
        ),

        "categories_legacy": (
            legacy_categories_value
        ),

        "base_image": (
            base_image
        ),

        "additional_images": (
            idb[
                "additional_images"
            ]
            if idb is not None
            else ""
        ),

        "legacy_images": (
            " | ".join(
                legacy_images
            )
        ),

        "legacy_skus": (
            " | ".join(
                legacy_skus
            )
        ),

        "legacy_eans": (
            " | ".join(
                legacy_eans
            )
        ),

        "legacy_manufacturers": (
            " | ".join(
                legacy_manufacturers
            )
        ),

        "legacy_names": (
            " || ".join(
                legacy_names
            )
        ),

        "legacy_prices": (
            " | ".join(
                legacy_prices
            )
        ),

        "source_count": (
            len(source_keys)
        ),

        "source_keys": (
            " | ".join(
                source_keys
            )
        ),

        "review_candidate_count": (
            len(review_candidates)
        ),

        "review_flags": (
            " | ".join(flags)
        ),

        "url_key": (
            idb["url_key"]
            if idb is not None
            else ""
        ),

        "meta_title": (
            idb["meta_title"]
            if idb is not None
            else ""
        ),

        "meta_description": (
            idb["meta_description"]
            if idb is not None
            else ""
        ),
    }


#
# --------------------------------------------------
# Build all Golden Records
# --------------------------------------------------
#

golden = []
source_links = []


#
# 1. Every Identbase product exactly once.
#
for sku in sorted(identbase):

    idb = identbase[sku]

    match = safe_by_idb.get(
        sku
    )

    group = None

    if match is not None:
        group = interaktiv[
            match[
                "interaktiv_group_id"
            ]
        ]

    row = build_golden(
        idb=idb,
        group=group,
        match=match,
    )

    golden.append(row)


#
# 2. Every Interaktiv group without SAFE
#    Identbase match becomes its own record.
#
for group_id in sorted(interaktiv):

    if group_id in safe_by_group:
        continue

    group = interaktiv[
        group_id
    ]

    row = build_golden(
        idb=None,
        group=group,
        match=None,
    )

    golden.append(row)


#
# --------------------------------------------------
# Source link table
# --------------------------------------------------
#

for row in golden:

    golden_id = row[
        "golden_id"
    ]

    if row["identbase_sku"]:

        idb = identbase[
            row["identbase_sku"]
        ]

        source_links.append({
            "golden_id": golden_id,
            "source": "identbase",
            "source_key": (
                "identbase:"
                + idb["sku"]
            ),
            "master_id": "",
            "sku": idb["sku"],
            "mpn": idb["mpn"],
            "ean": "",
            "name": idb["name_de"],
        })

    if row[
        "interaktiv_group_id"
    ]:

        group = interaktiv[
            row[
                "interaktiv_group_id"
            ]
        ]

        for legacy in (
            records_for_group(
                group
            )
        ):

            source_links.append({
                "golden_id": golden_id,
                "source": (
                    legacy["source"]
                ),
                "source_key": (
                    f"{legacy['source']}:"
                    f"{legacy['master_id']}"
                ),
                "master_id": (
                    legacy["master_id"]
                ),
                "sku": (
                    legacy["sku"]
                ),
                "mpn": "",
                "ean": (
                    legacy["ean"]
                ),
                "name": (
                    legacy["name"]
                ),
            })


#
# --------------------------------------------------
# Review links
# --------------------------------------------------
#

review_links = []

for review in review_rows:

    idb_sku = (
        review["identbase_sku"]
    )

    group_id = (
        review[
            "interaktiv_group_id"
        ]
    )

    idb_golden_id = stable_id(
        "IDB",
        "identbase:"
        + idb_sku
    )

    int_golden_id = stable_id(
        "INT",
        "interaktiv:"
        + group_id
    )

    #
    # If either side was already safely
    # merged elsewhere, note that fact.
    #
    idb_safe = (
        idb_sku in safe_by_idb
    )

    group_safe = (
        group_id in safe_by_group
    )

    review_links.append({
        "identbase_sku": (
            idb_sku
        ),

        "interaktiv_group_id": (
            group_id
        ),

        "identbase_golden_id": (
            idb_golden_id
        ),

        "interaktiv_golden_id": (
            int_golden_id
        ),

        "classification": (
            review["classification"]
        ),

        "name_similarity": (
            review[
                "name_similarity"
            ]
        ),

        "manufacturer_match": (
            review[
                "manufacturer_match"
            ]
        ),

        "identbase_already_safe": (
            "1"
            if idb_safe
            else "0"
        ),

        "interaktiv_already_safe": (
            "1"
            if group_safe
            else "0"
        ),

        "identbase_name": (
            review[
                "identbase_name"
            ]
        ),

        "interaktiv_names": (
            review[
                "interaktiv_names"
            ]
        ),

        "reason": (
            review["reason"]
        ),
    })


#
# --------------------------------------------------
# Validation
# --------------------------------------------------
#

expected_golden = (
    len(identbase)
    + len(interaktiv)
    - len(safe_rows)
)

if len(golden) != expected_golden:
    raise RuntimeError(
        "Golden count mismatch: "
        f"{len(golden)} != "
        f"{expected_golden}"
    )


golden_ids = [
    row["golden_id"]
    for row in golden
]

if len(golden_ids) != len(
    set(golden_ids)
):
    raise RuntimeError(
        "Duplicate golden_id"
    )


record_counts = Counter(
    row["record_type"]
    for row in golden
)


#
# Critical price authority check.
#
bad_legacy_prices = [
    row
    for row in golden
    if (
        row["record_type"]
        == "INTERAKTIV_ONLY"
        and row["effective_price"]
    )
]

if bad_legacy_prices:
    raise RuntimeError(
        "Interaktiv-only record "
        "has canonical price"
    )


#
# --------------------------------------------------
# Write files
# --------------------------------------------------
#

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


golden_fields = list(
    golden[0].keys()
)

with (
    OUTPUT_DIR
    / "golden_products.csv"
).open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=golden_fields,
    )

    writer.writeheader()
    writer.writerows(golden)


source_fields = list(
    source_links[0].keys()
)

with (
    OUTPUT_DIR
    / "source_links.csv"
).open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=source_fields,
    )

    writer.writeheader()
    writer.writerows(source_links)


if review_links:

    review_fields = list(
        review_links[0].keys()
    )

    with (
        OUTPUT_DIR
        / "review_links.csv"
    ).open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=review_fields,
        )

        writer.writeheader()
        writer.writerows(
            review_links
        )


#
# --------------------------------------------------
# Summary
# --------------------------------------------------
#

price_ok = sum(
    1
    for row in golden
    if row["price_status"] == "OK"
)

price_missing_idb = sum(
    1
    for row in golden
    if row["price_status"]
    == "REVIEW_IDENTBASE_PRICE_MISSING"
)

no_identbase_price = sum(
    1
    for row in golden
    if row["price_status"]
    == "REVIEW_NO_IDENTBASE_PRICE"
)

possible_match = sum(
    1
    for row in golden
    if (
        "REVIEW_POSSIBLE_MATCH"
        in row["review_flags"]
    )
)


print()
print(
    "===== GOLDEN RECORD ====="
)

print(
    f"Identbase products:        "
    f"{len(identbase)}"
)

print(
    f"Interaktiv groups:         "
    f"{len(interaktiv)}"
)

print(
    f"SAFE matches:              "
    f"{len(safe_rows)}"
)

print()

print(
    f"Golden products:           "
    f"{len(golden)}"
)

for record_type in (
    "IDENTBASE_MATCHED",
    "IDENTBASE_ONLY",
    "INTERAKTIV_ONLY",
):
    print(
        f"{record_type:26}"
        f"{record_counts[record_type]}"
    )

print()
print(
    f"Price OK / Identbase:      "
    f"{price_ok}"
)

print(
    f"Identbase price missing:   "
    f"{price_missing_idb}"
)

print(
    f"No Identbase price:        "
    f"{no_identbase_price}"
)

print(
    f"Records with review link:  "
    f"{possible_match}"
)

print()

print(
    f"Source links:              "
    f"{len(source_links)}"
)

print(
    f"Remaining review pairs:    "
    f"{len(review_links)}"
)

print()
print("Output:")
print(OUTPUT_DIR)
