#!/usr/bin/env python3

import csv
import re
import unicodedata
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

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

OUTPUT_DIR = (
    BASE
    / "working"
    / "identbase_matching"
)


SHOPS = (
    "identible",
    "cardnext",
    "inplastor",
)


def normalize_identifier(value):
    value = (value or "").strip().lower()

    return re.sub(
        r"\s+",
        "",
        value
    )


def normalize_text(value):
    value = (value or "").strip().lower()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
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


def similarity(a, b):
    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


def load_identbase():
    result = []

    with IDENTBASE_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as handle:

        for row in csv.DictReader(handle):

            row["sku_norm"] = (
                normalize_identifier(
                    row["sku"]
                )
            )

            row["mpn_norm"] = (
                normalize_identifier(
                    row["mpn"]
                )
            )

            row["name_norm"] = (
                normalize_text(
                    row["name_de"]
                )
            )

            row["manufacturer_norm"] = (
                normalize_text(
                    row["manufacturer"]
                )
            )

            result.append(row)

    return result


def load_interaktiv():
    result = []

    with INTERAKTIV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as handle:

        for row in csv.DictReader(handle):

            skus = []
            names = []
            manufacturers = []

            for shop in SHOPS:

                sku = (
                    row.get(
                        f"{shop}_sku",
                        ""
                    )
                    or ""
                ).strip()

                name = (
                    row.get(
                        f"{shop}_name",
                        ""
                    )
                    or ""
                ).strip()

                manufacturer = (
                    row.get(
                        f"{shop}_manufacturer",
                        ""
                    )
                    or ""
                ).strip()

                if sku and sku not in skus:
                    skus.append(sku)

                if name and name not in names:
                    names.append(name)

                if (
                    manufacturer
                    and manufacturer
                    not in manufacturers
                ):
                    manufacturers.append(
                        manufacturer
                    )

            row["all_skus"] = skus

            row["all_skus_norm"] = {
                normalize_identifier(x)
                for x in skus
                if normalize_identifier(x)
            }

            row["all_names"] = names

            row["all_names_norm"] = {
                normalize_text(x)
                for x in names
                if normalize_text(x)
            }

            row["all_manufacturers"] = (
                manufacturers
            )

            row["all_manufacturers_norm"] = {
                normalize_text(x)
                for x in manufacturers
                if normalize_text(x)
            }

            result.append(row)

    return result


def write_csv(
    path,
    rows,
    fieldnames=None
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if fieldnames is None:

        if not rows:
            return

        fieldnames = list(
            rows[0].keys()
        )

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


def max_name_similarity(
    identbase_product,
    interaktiv_group
):
    best = 0.0

    for legacy_name in (
        interaktiv_group[
            "all_names_norm"
        ]
    ):
        score = similarity(
            identbase_product[
                "name_norm"
            ],
            legacy_name
        )

        if score > best:
            best = score

    return best


def manufacturer_match(
    identbase_product,
    interaktiv_group
):
    manufacturer = (
        identbase_product[
            "manufacturer_norm"
        ]
    )

    if not manufacturer:
        return False

    if (
        manufacturer
        in interaktiv_group[
            "all_manufacturers_norm"
        ]
    ):
        return True

    #
    # Small, deliberate normalization
    # for common brand spelling.
    #
    aliases = {
        "fargo": "hid fargo",
        "hid fargo": "fargo",
    }

    alias = aliases.get(
        manufacturer
    )

    if (
        alias
        and alias
        in interaktiv_group[
            "all_manufacturers_norm"
        ]
    ):
        return True

    return False


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    identbase = load_identbase()
    interaktiv = load_interaktiv()

    #
    # Build indexes over all legacy SKUs
    # and names.
    #
    sku_index = defaultdict(set)
    name_index = defaultdict(set)

    group_lookup = {}

    for group in interaktiv:

        group_id = (
            group[
                "interaktiv_group_id"
            ]
        )

        group_lookup[group_id] = group

        for sku in group[
            "all_skus_norm"
        ]:
            sku_index[sku].add(
                group_id
            )

        for name in group[
            "all_names_norm"
        ]:
            name_index[name].add(
                group_id
            )

    #
    # Candidate pairs.
    #
    candidates = {}

    def add_candidate(
        product,
        group_id,
        evidence
    ):
        key = (
            product["sku"],
            group_id
        )

        if key not in candidates:

            group = group_lookup[
                group_id
            ]

            candidates[key] = {
                "identbase_sku": (
                    product["sku"]
                ),
                "identbase_mpn": (
                    product["mpn"]
                ),
                "identbase_name": (
                    product["name_de"]
                ),
                "identbase_manufacturer": (
                    product[
                        "manufacturer"
                    ]
                ),
                "identbase_price": (
                    product[
                        "effective_price"
                    ]
                ),

                "interaktiv_group_id": (
                    group_id
                ),

                "interaktiv_skus": (
                    " | ".join(
                        group[
                            "all_skus"
                        ]
                    )
                ),

                "interaktiv_names": (
                    " || ".join(
                        group[
                            "all_names"
                        ]
                    )
                ),

                "interaktiv_manufacturers": (
                    " | ".join(
                        group[
                            "all_manufacturers"
                        ]
                    )
                ),

                "evidence": set(),

                "name_similarity": (
                    max_name_similarity(
                        product,
                        group
                    )
                ),

                "manufacturer_match": (
                    manufacturer_match(
                        product,
                        group
                    )
                ),
            }

        candidates[key][
            "evidence"
        ].add(evidence)

    for product in identbase:

        sku = product[
            "sku_norm"
        ]

        mpn = product[
            "mpn_norm"
        ]

        name = product[
            "name_norm"
        ]

        #
        # Identbase SKU == old shop SKU
        #
        if sku:

            for group_id in (
                sku_index.get(
                    sku,
                    set()
                )
            ):
                add_candidate(
                    product,
                    group_id,
                    "SKU_EXACT"
                )

        #
        # Identbase manufacturer part number
        # == old shop SKU
        #
        if mpn:

            for group_id in (
                sku_index.get(
                    mpn,
                    set()
                )
            ):
                add_candidate(
                    product,
                    group_id,
                    "MPN_TO_LEGACY_SKU"
                )

        #
        # Exact normalized name.
        # Only review evidence, never enough
        # on its own for auto matching.
        #
        if name:

            for group_id in (
                name_index.get(
                    name,
                    set()
                )
            ):
                add_candidate(
                    product,
                    group_id,
                    "NAME_EXACT"
                )

    #
    # Candidate counts on both sides.
    #
    by_identbase = defaultdict(set)
    by_group = defaultdict(set)

    for (
        identbase_sku,
        group_id
    ) in candidates:

        by_identbase[
            identbase_sku
        ].add(group_id)

        by_group[
            group_id
        ].add(
            identbase_sku
        )

    safe = []
    review = []

    evidence_counts = Counter()

    for key, candidate in (
        sorted(
            candidates.items()
        )
    ):

        identbase_sku, group_id = key

        evidence = candidate[
            "evidence"
        ]

        name_score = candidate[
            "name_similarity"
        ]

        manufacturer_same = (
            candidate[
                "manufacturer_match"
            ]
        )

        idb_count = len(
            by_identbase[
                identbase_sku
            ]
        )

        group_count = len(
            by_group[
                group_id
            ]
        )

        one_to_one = (
            idb_count == 1
            and group_count == 1
        )

        classification = ""
        confidence = 0
        reason = ""

        #
        # Strongest:
        # Magento SKU found directly in
        # a legacy shop.
        #
        if "SKU_EXACT" in evidence:

            if (
                one_to_one
                and (
                    name_score >= 0.45
                    or manufacturer_same
                    or "MPN_TO_LEGACY_SKU"
                    in evidence
                )
            ):
                classification = (
                    "SAFE_SKU"
                )
                confidence = 100

            else:
                classification = (
                    "REVIEW_SKU"
                )

                reason = (
                    "exact SKU but ambiguous "
                    "or weak product similarity"
                )

        #
        # Magento MPN matches a legacy SKU.
        #
        elif (
            "MPN_TO_LEGACY_SKU"
            in evidence
        ):

            if (
                one_to_one
                and (
                    name_score >= 0.45
                    or manufacturer_same
                )
            ):
                classification = (
                    "SAFE_MPN"
                )
                confidence = 98

            else:
                classification = (
                    "REVIEW_MPN"
                )

                reason = (
                    "MPN matches legacy SKU "
                    "but match is ambiguous "
                    "or weak"
                )

        #
        # Exact name only is review.
        #
        else:

            classification = (
                "REVIEW_NAME"
            )

            reason = (
                "exact name without "
                "matching SKU or MPN"
            )

        row = {
            "classification": (
                classification
            ),

            "confidence": confidence,

            "identbase_sku": (
                candidate[
                    "identbase_sku"
                ]
            ),

            "identbase_mpn": (
                candidate[
                    "identbase_mpn"
                ]
            ),

            "identbase_name": (
                candidate[
                    "identbase_name"
                ]
            ),

            "identbase_manufacturer": (
                candidate[
                    "identbase_manufacturer"
                ]
            ),

            "identbase_price": (
                candidate[
                    "identbase_price"
                ]
            ),

            "interaktiv_group_id": (
                candidate[
                    "interaktiv_group_id"
                ]
            ),

            "interaktiv_skus": (
                candidate[
                    "interaktiv_skus"
                ]
            ),

            "interaktiv_names": (
                candidate[
                    "interaktiv_names"
                ]
            ),

            "interaktiv_manufacturers": (
                candidate[
                    "interaktiv_manufacturers"
                ]
            ),

            "evidence": (
                " | ".join(
                    sorted(evidence)
                )
            ),

            "name_similarity": (
                round(
                    name_score,
                    4
                )
            ),

            "manufacturer_match": (
                "1"
                if manufacturer_same
                else "0"
            ),

            "identbase_candidate_groups": (
                idb_count
            ),

            "group_candidate_identbase": (
                group_count
            ),

            "reason": reason,
        }

        evidence_counts[
            classification
        ] += 1

        if classification.startswith(
            "SAFE_"
        ):
            safe.append(row)
        else:
            review.append(row)

    #
    # Determine safely matched products/groups.
    #
    safe_identbase = {
        row["identbase_sku"]
        for row in safe
    }

    safe_groups = {
        row["interaktiv_group_id"]
        for row in safe
    }

    unmatched_identbase = []

    for product in identbase:

        if (
            product["sku"]
            not in safe_identbase
        ):
            unmatched_identbase.append({
                "sku": product["sku"],
                "mpn": product["mpn"],
                "manufacturer": (
                    product[
                        "manufacturer"
                    ]
                ),
                "name": (
                    product["name_de"]
                ),
                "effective_price": (
                    product[
                        "effective_price"
                    ]
                ),
                "product_type": (
                    product[
                        "product_type"
                    ]
                ),
            })

    unmatched_interaktiv = []

    for group in interaktiv:

        group_id = (
            group[
                "interaktiv_group_id"
            ]
        )

        if group_id not in safe_groups:

            unmatched_interaktiv.append({
                "interaktiv_group_id": (
                    group_id
                ),

                "sources": (
                    group["sources"]
                ),

                "reference_sku": (
                    group[
                        "reference_sku"
                    ]
                ),

                "reference_name": (
                    group[
                        "reference_name"
                    ]
                ),

                "reference_manufacturer": (
                    group[
                        "reference_manufacturer"
                    ]
                ),

                "identible_sku": (
                    group.get(
                        "identible_sku",
                        ""
                    )
                ),

                "cardnext_sku": (
                    group.get(
                        "cardnext_sku",
                        ""
                    )
                ),

                "inplastor_sku": (
                    group.get(
                        "inplastor_sku",
                        ""
                    )
                ),
            })

    fields = [
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
    ]

    write_csv(
        OUTPUT_DIR
        / "safe_matches.csv",
        safe,
        fields
    )

    write_csv(
        OUTPUT_DIR
        / "review_matches.csv",
        review,
        fields
    )

    write_csv(
        OUTPUT_DIR
        / "unmatched_identbase.csv",
        unmatched_identbase
    )

    write_csv(
        OUTPUT_DIR
        / "unmatched_interaktiv.csv",
        unmatched_interaktiv
    )

    print()
    print(
        "===== IDENTBASE ↔ INTERAKTIV ====="
    )

    print(
        f"Identbase Produkte:         "
        f"{len(identbase)}"
    )

    print(
        f"Interaktiv Gruppen:         "
        f"{len(interaktiv)}"
    )

    print(
        f"Candidate pairs:            "
        f"{len(candidates)}"
    )

    print()

    for classification, count in (
        sorted(
            evidence_counts.items()
        )
    ):
        print(
            f"{classification:25} "
            f"{count}"
        )

    print()

    print(
        f"Sichere Matches:            "
        f"{len(safe)}"
    )

    print(
        f"Review-Paare:               "
        f"{len(review)}"
    )

    print(
        f"Sicher gematchte "
        f"Interaktiv-Gruppen:         "
        f"{len(safe_groups)}"
    )

    print(
        f"Ungematchte "
        f"Interaktiv-Gruppen:         "
        f"{len(unmatched_interaktiv)}"
    )

    print(
        f"Sicher gematchte "
        f"Identbase-Produkte:         "
        f"{len(safe_identbase)}"
    )

    print(
        f"Identbase ohne Safe Match:  "
        f"{len(unmatched_identbase)}"
    )

    print()
    print("Output:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
