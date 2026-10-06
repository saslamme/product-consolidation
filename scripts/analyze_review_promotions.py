#!/usr/bin/env python3

import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

REVIEW_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "review_matches.csv"
)

IDENTBASE_FILE = (
    BASE
    / "working"
    / "identbase"
    / "products.csv"
)

INTERAKTIV_FILE = (
    BASE
    / "working"
    / "interaktiv"
    / "merged"
    / "interaktiv_master_products.csv"
)

OUTPUT_FILE = (
    BASE
    / "working"
    / "identbase_matching"
    / "promotion_candidates.csv"
)


def norm(value):
    value = (value or "").strip().lower()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


ALIASES = {
    "fargo": "hid fargo",
    "hid fargo": "fargo",

    "datacard": "entrust",
    "entrust datacard": "entrust",
}


def manufacturer_state(
    identbase_value,
    legacy_values
):
    left = norm(
        identbase_value
    )

    rights = {
        norm(x)
        for x in legacy_values
        if norm(x)
    }

    if not left and not rights:
        return "BOTH_MISSING"

    if not left or not rights:
        return "ONE_MISSING"

    if left in rights:
        return "MATCH"

    alias = ALIASES.get(left)

    if alias and alias in rights:
        return "MATCH_ALIAS"

    reverse = {
        v: k
        for k, v in ALIASES.items()
    }

    alias = reverse.get(left)

    if alias and alias in rights:
        return "MATCH_ALIAS"

    return "CONFLICT"


#
# Identbase lookup.
#
identbase = {}

with IDENTBASE_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    for row in csv.DictReader(f):
        identbase[
            row["sku"]
        ] = row


#
# Interaktiv lookup.
#
interaktiv = {}

with INTERAKTIV_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    for row in csv.DictReader(f):

        manufacturers = []

        for shop in (
            "identible",
            "cardnext",
            "inplastor",
        ):
            value = (
                row.get(
                    f"{shop}_manufacturer",
                    ""
                )
                or ""
            ).strip()

            if (
                value
                and value not in manufacturers
            ):
                manufacturers.append(
                    value
                )

        row["_manufacturers"] = (
            manufacturers
        )

        interaktiv[
            row["interaktiv_group_id"]
        ] = row


with REVIEW_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    reviews = list(
        csv.DictReader(f)
    )


result = []
counts = Counter()


for row in reviews:

    idb = identbase[
        row["identbase_sku"]
    ]

    legacy = interaktiv[
        row["interaktiv_group_id"]
    ]

    similarity = float(
        row["name_similarity"]
        or 0
    )

    idb_candidates = int(
        row[
            "identbase_candidate_groups"
        ]
    )

    legacy_candidates = int(
        row[
            "group_candidate_identbase"
        ]
    )

    state = manufacturer_state(
        idb["manufacturer"],
        legacy["_manufacturers"]
    )

    recommendation = "KEEP_REVIEW"
    reason = ""

    #
    # New conservative safe rule:
    #
    # - NAME review only
    # - normalized name exactly identical
    # - candidate relation strictly 1:1
    # - no explicit manufacturer conflict
    #
    if (
        row["classification"]
        == "REVIEW_NAME"
        and similarity >= 0.9999
        and idb_candidates == 1
        and legacy_candidates == 1
        and state != "CONFLICT"
    ):
        recommendation = (
            "PROMOTE_SAFE_NAME_1TO1"
        )

        reason = (
            "exact name, unique 1:1 "
            "relationship, no manufacturer "
            "contradiction"
        )

    elif (
        row["classification"]
        == "REVIEW_NAME"
        and similarity >= 0.95
        and idb_candidates == 1
        and legacy_candidates == 1
        and state in {
            "MATCH",
            "MATCH_ALIAS",
        }
    ):
        recommendation = (
            "STRONG_REVIEW_NAME"
        )

        reason = (
            "very strong name similarity, "
            "unique 1:1, manufacturer agrees"
        )

    elif (
        state == "CONFLICT"
        and similarity >= 0.95
    ):
        recommendation = (
            "REVIEW_MANUFACTURER_CONFLICT"
        )

        reason = (
            "strong name similarity but "
            "manufacturer contradicts"
        )

    counts[recommendation] += 1

    result.append({
        "recommendation": (
            recommendation
        ),

        "reason": reason,

        "classification": (
            row["classification"]
        ),

        "identbase_sku": (
            row["identbase_sku"]
        ),

        "identbase_mpn": (
            row["identbase_mpn"]
        ),

        "identbase_name": (
            row["identbase_name"]
        ),

        "identbase_manufacturer": (
            idb["manufacturer"]
        ),

        "interaktiv_group_id": (
            row["interaktiv_group_id"]
        ),

        "interaktiv_skus": (
            row["interaktiv_skus"]
        ),

        "interaktiv_names": (
            row["interaktiv_names"]
        ),

        "interaktiv_manufacturers": (
            " | ".join(
                legacy[
                    "_manufacturers"
                ]
            )
        ),

        "manufacturer_state": (
            state
        ),

        "name_similarity": (
            row["name_similarity"]
        ),

        "identbase_candidate_groups": (
            idb_candidates
        ),

        "group_candidate_identbase": (
            legacy_candidates
        ),
    })


fields = [
    "recommendation",
    "reason",
    "classification",

    "identbase_sku",
    "identbase_mpn",
    "identbase_name",
    "identbase_manufacturer",

    "interaktiv_group_id",
    "interaktiv_skus",
    "interaktiv_names",
    "interaktiv_manufacturers",

    "manufacturer_state",
    "name_similarity",

    "identbase_candidate_groups",
    "group_candidate_identbase",
]


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
    writer.writerows(result)


print()
print(
    "===== REVIEW PROMOTION ANALYSIS ====="
)

for key, value in (
    counts.most_common()
):
    print(
        f"{key:35} {value}"
    )

print()
print("Output:")
print(OUTPUT_FILE)
