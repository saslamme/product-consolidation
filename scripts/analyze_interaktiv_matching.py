#!/usr/bin/env python3

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PRODUCT_DIR = BASE / "working" / "interaktiv" / "products"
REPORT_DIR = BASE / "working" / "interaktiv" / "matching"

SHOPS = ("identible", "inplastor", "cardnext")


def normalize(value):
    value = (value or "").strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_ean(value):
    return re.sub(r"[^0-9]", "", value or "")


def normalize_sku(value):
    value = (value or "").strip().lower()
    return re.sub(r"\s+", "", value)


def load(shop):
    path = PRODUCT_DIR / f"{shop}.csv"

    products = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        for row in csv.DictReader(f):
            row["source_key"] = (
                f"{shop}:{row['master_id']}"
            )
            row["sku_norm"] = normalize_sku(
                row["sku"]
            )
            row["ean_norm"] = normalize_ean(
                row["ean"]
            )
            row["name_norm"] = normalize(
                row["name"]
            )
            row["manufacturer_norm"] = normalize(
                row["manufacturer"]
            )

            products.append(row)

    return products


def index_unique(products, field):
    index = defaultdict(list)

    for product in products:
        value = product[field]

        if value:
            index[value].append(product)

    return {
        value: records[0]
        for value, records in index.items()
        if len(records) == 1
    }


def index_all(products, field):
    result = defaultdict(list)

    for product in products:
        value = product[field]

        if value:
            result[value].append(product)

    return result


def write_csv(path, rows):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not rows:
        return

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


def analyze_pair(shop_a, shop_b, data):
    a = data[shop_a]
    b = data[shop_b]

    a_by_master = {
        p["master_id"]: p for p in a
    }
    b_by_master = {
        p["master_id"]: p for p in b
    }

    same_master = (
        set(a_by_master)
        & set(b_by_master)
    )

    same_master_same_sku = []
    same_master_diff_sku = []

    for master_id in sorted(same_master):
        pa = a_by_master[master_id]
        pb = b_by_master[master_id]

        record = {
            "master_id": master_id,
            f"{shop_a}_key": pa["source_key"],
            f"{shop_a}_sku": pa["sku"],
            f"{shop_a}_ean": pa["ean"],
            f"{shop_a}_name": pa["name"],
            f"{shop_b}_key": pb["source_key"],
            f"{shop_b}_sku": pb["sku"],
            f"{shop_b}_ean": pb["ean"],
            f"{shop_b}_name": pb["name"],
        }

        if (
            pa["sku_norm"]
            and pa["sku_norm"] == pb["sku_norm"]
        ):
            same_master_same_sku.append(record)
        else:
            same_master_diff_sku.append(record)

    a_ean = index_unique(a, "ean_norm")
    b_ean = index_unique(b, "ean_norm")

    exact_ean = []

    for value in sorted(
        set(a_ean) & set(b_ean)
    ):
        pa = a_ean[value]
        pb = b_ean[value]

        exact_ean.append({
            "match_method": "EAN",
            "value": value,
            f"{shop_a}_key": pa["source_key"],
            f"{shop_a}_sku": pa["sku"],
            f"{shop_a}_name": pa["name"],
            f"{shop_b}_key": pb["source_key"],
            f"{shop_b}_sku": pb["sku"],
            f"{shop_b}_name": pb["name"],
        })

    a_sku = index_unique(a, "sku_norm")
    b_sku = index_unique(b, "sku_norm")

    exact_sku = []

    for value in sorted(
        set(a_sku) & set(b_sku)
    ):
        pa = a_sku[value]
        pb = b_sku[value]

        exact_sku.append({
            "match_method": "SKU",
            "value": value,
            f"{shop_a}_key": pa["source_key"],
            f"{shop_a}_ean": pa["ean"],
            f"{shop_a}_name": pa["name"],
            f"{shop_b}_key": pb["source_key"],
            f"{shop_b}_ean": pb["ean"],
            f"{shop_b}_name": pb["name"],
        })

    a_names = index_unique(a, "name_norm")
    b_names = index_unique(b, "name_norm")

    exact_name = []

    for value in sorted(
        set(a_names) & set(b_names)
    ):
        pa = a_names[value]
        pb = b_names[value]

        exact_name.append({
            "match_method": "NAME",
            f"{shop_a}_key": pa["source_key"],
            f"{shop_a}_sku": pa["sku"],
            f"{shop_a}_ean": pa["ean"],
            f"{shop_b}_key": pb["source_key"],
            f"{shop_b}_sku": pb["sku"],
            f"{shop_b}_ean": pb["ean"],
            "name": pa["name"],
        })

    name = f"{shop_a}__{shop_b}"

    write_csv(
        REPORT_DIR
        / f"{name}_master_same_sku.csv",
        same_master_same_sku
    )

    write_csv(
        REPORT_DIR
        / f"{name}_master_conflicts.csv",
        same_master_diff_sku
    )

    write_csv(
        REPORT_DIR
        / f"{name}_exact_ean.csv",
        exact_ean
    )

    write_csv(
        REPORT_DIR
        / f"{name}_exact_sku.csv",
        exact_sku
    )

    write_csv(
        REPORT_DIR
        / f"{name}_exact_name.csv",
        exact_name
    )

    print()
    print(
        f"===== {shop_a.upper()} "
        f"<-> {shop_b.upper()} ====="
    )

    print(
        f"Master-ID Überschneidung:        "
        f"{len(same_master)}"
    )

    print(
        f"Master-ID + gleiche SKU:         "
        f"{len(same_master_same_sku)}"
    )

    print(
        f"Master-ID + unterschiedliche SKU:"
        f" {len(same_master_diff_sku)}"
    )

    print(
        f"Eindeutige exakte EAN-Matches:   "
        f"{len(exact_ean)}"
    )

    print(
        f"Eindeutige exakte SKU-Matches:   "
        f"{len(exact_sku)}"
    )

    print(
        f"Eindeutige exakte Name-Matches:  "
        f"{len(exact_name)}"
    )


def ean_statistics(shop, products):
    by_ean = index_all(
        products,
        "ean_norm"
    )

    nonempty = {
        ean: records
        for ean, records in by_ean.items()
        if ean
    }

    duplicates = {
        ean: records
        for ean, records in nonempty.items()
        if len(records) > 1
    }

    print()
    print(f"===== EAN {shop.upper()} =====")
    print(
        f"Produkte gesamt:        "
        f"{len(products)}"
    )
    print(
        f"Eindeutige EAN-Werte:   "
        f"{len(nonempty)}"
    )
    print(
        f"Doppelt verwendete EAN: "
        f"{len(duplicates)}"
    )

    rows = []

    for ean, records in duplicates.items():
        rows.append({
            "ean": ean,
            "products": len(records),
            "source_keys": " | ".join(
                r["source_key"]
                for r in records
            ),
            "skus": " | ".join(
                r["sku"]
                for r in records
            ),
            "names": " || ".join(
                r["name"]
                for r in records
            ),
        })

    write_csv(
        REPORT_DIR
        / f"{shop}_duplicate_eans.csv",
        rows
    )


def main():
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    data = {
        shop: load(shop)
        for shop in SHOPS
    }

    for shop in SHOPS:
        ean_statistics(
            shop,
            data[shop]
        )

    analyze_pair(
        "identible",
        "cardnext",
        data
    )

    analyze_pair(
        "identible",
        "inplastor",
        data
    )

    analyze_pair(
        "cardnext",
        "inplastor",
        data
    )

    print()
    print("Reports:")
    print(REPORT_DIR)


if __name__ == "__main__":
    main()
