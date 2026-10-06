#!/usr/bin/env python3

import csv
import hashlib
import itertools
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

PRODUCT_DIR = (
    BASE
    / "working"
    / "interaktiv"
    / "products"
)

OUTPUT_DIR = (
    BASE
    / "working"
    / "interaktiv"
    / "merged"
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


def normalize_sku(value):
    return re.sub(
        r"\s+",
        "",
        (value or "").strip().lower()
    )


def normalize_ean(value):
    return re.sub(
        r"[^0-9]",
        "",
        value or ""
    )


def name_similarity(a, b):
    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


def load_products():
    products = {}

    for shop in SHOPS:
        path = PRODUCT_DIR / f"{shop}.csv"

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as handle:

            for row in csv.DictReader(handle):
                key = (
                    f"{shop}:"
                    f"{row['master_id']}"
                )

                row["source"] = shop
                row["source_key"] = key

                row["sku_norm"] = normalize_sku(
                    row["sku"]
                )

                row["ean_norm"] = normalize_ean(
                    row["ean"]
                )

                row["name_norm"] = normalize_text(
                    row["name"]
                )

                row["manufacturer_norm"] = (
                    normalize_text(
                        row["manufacturer"]
                    )
                )

                products[key] = row

    return products


class UnionFind:

    def __init__(self, products):
        self.products = products
        self.parent = {}
        self.sources = {}
        self.eans = {}

        for key, product in products.items():
            self.parent[key] = key

            self.sources[key] = {
                product["source"]
            }

            ean = product["ean_norm"]

            self.eans[key] = (
                {ean}
                if ean
                else set()
            )

    def find(self, key):
        if self.parent[key] != key:
            self.parent[key] = self.find(
                self.parent[key]
            )

        return self.parent[key]

    def check_union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)

        if ra == rb:
            return True, "already_grouped"

        sources_a = self.sources[ra]
        sources_b = self.sources[rb]

        if sources_a & sources_b:
            return False, "same_source_collision"

        eans = (
            self.eans[ra]
            | self.eans[rb]
        )

        if len(eans) > 1:
            return False, "conflicting_ean"

        return True, ""

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)

        if ra == rb:
            return ra

        self.parent[rb] = ra

        self.sources[ra] |= (
            self.sources[rb]
        )

        self.eans[ra] |= (
            self.eans[rb]
        )

        return ra


def build_index(products, field):
    index = defaultdict(list)

    for product in products.values():
        value = product[field]

        if value:
            index[value].append(product)

    return index


def valid_cross_source_group(records):
    counts = defaultdict(int)

    for record in records:
        counts[record["source"]] += 1

    return all(
        count == 1
        for count in counts.values()
    )


def add_group_pairs(
    candidates,
    records,
    rule,
    confidence,
):
    for left, right in itertools.combinations(
        records,
        2
    ):
        if (
            left["source"]
            == right["source"]
        ):
            continue

        candidates.append({
            "left": left["source_key"],
            "right": right["source_key"],
            "rule": rule,
            "confidence": confidence,
            "name_similarity": round(
                name_similarity(
                    left["name_norm"],
                    right["name_norm"]
                ),
                4
            ),
        })


def build_candidates(products):
    candidates = []
    review = []

    #
    # Rule 1:
    # Unique exact EAN across shops.
    #
    ean_index = build_index(
        products,
        "ean_norm"
    )

    for ean, records in ean_index.items():

        if len({
            r["source"]
            for r in records
        }) < 2:
            continue

        if not valid_cross_source_group(
            records
        ):
            continue

        add_group_pairs(
            candidates,
            records,
            "EAN_EXACT",
            100,
        )

    #
    # Rule 2:
    # Identible ↔ Cardnext:
    # same master ID + same SKU.
    #
    identible = {
        p["master_id"]: p
        for p in products.values()
        if p["source"] == "identible"
    }

    cardnext = {
        p["master_id"]: p
        for p in products.values()
        if p["source"] == "cardnext"
    }

    for master_id in (
        set(identible)
        & set(cardnext)
    ):
        left = identible[master_id]
        right = cardnext[master_id]

        if (
            left["sku_norm"]
            and left["sku_norm"]
            == right["sku_norm"]
        ):
            candidates.append({
                "left": left["source_key"],
                "right": right["source_key"],
                "rule": "IDENTIBLE_CARDNEXT_ID_SKU",
                "confidence": 99,
                "name_similarity": round(
                    name_similarity(
                        left["name_norm"],
                        right["name_norm"]
                    ),
                    4
                ),
            })

    #
    # Rule 3:
    # Unique exact SKU across shops.
    #
    sku_index = build_index(
        products,
        "sku_norm"
    )

    for sku, records in sku_index.items():

        if len({
            r["source"]
            for r in records
        }) < 2:
            continue

        if not valid_cross_source_group(
            records
        ):
            continue

        for left, right in itertools.combinations(
            records,
            2
        ):
            if (
                left["source"]
                == right["source"]
            ):
                continue

            similarity = name_similarity(
                left["name_norm"],
                right["name_norm"]
            )

            same_manufacturer = (
                left["manufacturer_norm"]
                and left["manufacturer_norm"]
                == right["manufacturer_norm"]
            )

            same_name = (
                left["name_norm"]
                and left["name_norm"]
                == right["name_norm"]
            )

            #
            # A matching unique SKU is strong,
            # but protect against obvious
            # recycled/mistyped SKUs.
            #
            if (
                similarity >= 0.50
                or same_manufacturer
                or same_name
            ):
                candidates.append({
                    "left": left["source_key"],
                    "right": right["source_key"],
                    "rule": "SKU_EXACT",
                    "confidence": 95,
                    "name_similarity": round(
                        similarity,
                        4
                    ),
                })
            else:
                review.append({
                    "rule": "SKU_EXACT_WEAK_NAME",
                    "left": left["source_key"],
                    "right": right["source_key"],
                    "left_sku": left["sku"],
                    "right_sku": right["sku"],
                    "left_ean": left["ean"],
                    "right_ean": right["ean"],
                    "left_name": left["name"],
                    "right_name": right["name"],
                    "name_similarity": round(
                        similarity,
                        4
                    ),
                    "reason": (
                        "same SKU but weak "
                        "product similarity"
                    ),
                })

    #
    # Rule 4:
    # Exact normalized product name.
    #
    name_index = build_index(
        products,
        "name_norm"
    )

    for name, records in name_index.items():

        if len({
            r["source"]
            for r in records
        }) < 2:
            continue

        if not valid_cross_source_group(
            records
        ):
            continue

        add_group_pairs(
            candidates,
            records,
            "NAME_EXACT",
            90,
        )

    #
    # Higher-confidence rules first.
    #
    candidates.sort(
        key=lambda x: (
            -x["confidence"],
            x["left"],
            x["right"],
            x["rule"],
        )
    )

    return candidates, review


def write_csv(
    path,
    rows,
    fieldnames=None,
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
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def process_candidates(
    products,
    candidates,
    pre_review,
):
    uf = UnionFind(products)

    accepted = []
    rejected = list(pre_review)

    for candidate in candidates:

        left = candidate["left"]
        right = candidate["right"]

        allowed, reason = (
            uf.check_union(
                left,
                right
            )
        )

        if allowed:

            already = (
                uf.find(left)
                == uf.find(right)
            )

            if not already:
                uf.union(
                    left,
                    right
                )

            accepted.append({
                **candidate,
                "result": (
                    "support"
                    if already
                    else "merged"
                ),
            })

        else:

            lp = products[left]
            rp = products[right]

            rejected.append({
                "rule": candidate["rule"],
                "left": left,
                "right": right,
                "left_sku": lp["sku"],
                "right_sku": rp["sku"],
                "left_ean": lp["ean"],
                "right_ean": rp["ean"],
                "left_name": lp["name"],
                "right_name": rp["name"],
                "name_similarity": (
                    candidate[
                        "name_similarity"
                    ]
                ),
                "reason": reason,
            })

    return uf, accepted, rejected


def choose_reference(records):
    return sorted(
        records,
        key=lambda x: (
            SOURCE_PRIORITY[
                x["source"]
            ],
            x["source_key"],
        )
    )[0]


def build_master_rows(
    products,
    uf,
    accepted,
):
    groups = defaultdict(list)

    for key, product in products.items():
        root = uf.find(key)
        groups[root].append(product)

    methods_by_root = defaultdict(set)
    confidence_by_root = defaultdict(list)

    for edge in accepted:
        root = uf.find(
            edge["left"]
        )

        methods_by_root[root].add(
            edge["rule"]
        )

        if edge["result"] == "merged":
            confidence_by_root[root].append(
                edge["confidence"]
            )

    rows = []

    for root, records in groups.items():

        records = sorted(
            records,
            key=lambda x: (
                SOURCE_PRIORITY[
                    x["source"]
                ],
                x["source_key"],
            )
        )

        reference = choose_reference(
            records
        )

        source_keys = sorted(
            r["source_key"]
            for r in records
        )

        digest = hashlib.sha1(
            "|".join(
                source_keys
            ).encode("utf-8")
        ).hexdigest()[:10].upper()

        group_id = f"INT-{digest}"

        methods = sorted(
            methods_by_root[root]
        )

        confidence_values = (
            confidence_by_root[root]
        )

        confidence = (
            min(confidence_values)
            if confidence_values
            else 0
        )

        row = {
            "interaktiv_group_id": group_id,
            "source_count": len(records),
            "sources": " | ".join(
                r["source"]
                for r in records
            ),
            "match_confidence": confidence,
            "match_methods": " | ".join(
                methods
            ),
            "reference_sku": (
                reference["sku"]
            ),
            "reference_ean": (
                reference["ean"]
            ),
            "reference_name": (
                reference["name"]
            ),
            "reference_manufacturer": (
                reference["manufacturer"]
            ),
        }

        for shop in SHOPS:

            record = next(
                (
                    r
                    for r in records
                    if r["source"]
                    == shop
                ),
                None
            )

            prefix = shop

            fields = (
                "master_id",
                "sku",
                "ean",
                "name",
                "price",
                "manufacturer",
                "image",
                "categories",
            )

            for field_name in fields:
                row[
                    f"{prefix}_{field_name}"
                ] = (
                    record.get(
                        field_name,
                        ""
                    )
                    if record
                    else ""
                )

        rows.append(row)

    rows.sort(
        key=lambda x: (
            x["reference_sku"].lower(),
            x["reference_name"].lower(),
            x["interaktiv_group_id"],
        )
    )

    return rows


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    products = load_products()

    candidates, pre_review = (
        build_candidates(products)
    )

    uf, accepted, rejected = (
        process_candidates(
            products,
            candidates,
            pre_review,
        )
    )

    master_rows = build_master_rows(
        products,
        uf,
        accepted,
    )

    write_csv(
        OUTPUT_DIR
        / "interaktiv_master_products.csv",
        master_rows
    )

    write_csv(
        OUTPUT_DIR
        / "accepted_matches.csv",
        accepted,
        fieldnames=[
            "left",
            "right",
            "rule",
            "confidence",
            "name_similarity",
            "result",
        ],
    )

    write_csv(
        OUTPUT_DIR
        / "review_matches.csv",
        rejected,
        fieldnames=[
            "rule",
            "left",
            "right",
            "left_sku",
            "right_sku",
            "left_ean",
            "right_ean",
            "left_name",
            "right_name",
            "name_similarity",
            "reason",
        ],
    )

    source_counts = defaultdict(int)

    for row in master_rows:
        source_counts[
            row["source_count"]
        ] += 1

    print()
    print(
        "===== INTERAKTIV MERGE ====="
    )

    print(
        f"Quellprodukte:        "
        f"{len(products)}"
    )

    print(
        f"Produktgruppen:       "
        f"{len(master_rows)}"
    )

    print(
        f"Singletons:           "
        f"{source_counts[1]}"
    )

    print(
        f"In 2 Shops:           "
        f"{source_counts[2]}"
    )

    print(
        f"In allen 3 Shops:     "
        f"{source_counts[3]}"
    )

    print(
        f"Akzeptierte Evidenzen:"
        f" {len(accepted)}"
    )

    print(
        f"Review-Fälle:         "
        f"{len(rejected)}"
    )

    print()
    print("Output:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
