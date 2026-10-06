#!/usr/bin/env python3

import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

SHOPS = ("identible", "inplastor", "cardnext")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"
WORKING_DIR = BASE_DIR / "working" / "interaktiv"
ROWS_DIR = WORKING_DIR / "rows"
PRODUCTS_DIR = WORKING_DIR / "products"
REPORTS_DIR = WORKING_DIR / "reports"

EXPECTED_FIELDS = 62

# 1-based interaktiv.net field numbers
FIELD = {
    "row_id": 1,
    "category_1": 2,
    "category_2": 3,
    "sku": 4,
    "name": 5,
    "price": 6,
    "description": 7,
    "image": 13,
    "manufacturer": 18,
    "category_path_raw": 23,
    "master_id": 30,
    "seo_title": 31,
    "ean": 36,
    "timestamps": 41,
}


def field(fields, number):
    """Return a 1-based field safely."""
    index = number - 1
    if index >= len(fields):
        return ""
    return fields[index].strip()


def normalize_price(value):
    value = value.strip()

    if not value:
        return ""

    value = value.replace(",", ".")

    try:
        number = Decimal(value)
        return format(number.quantize(Decimal("0.01")), "f")
    except InvalidOperation:
        return value


def category_path(fields):
    level1 = field(fields, FIELD["category_1"])
    level2 = field(fields, FIELD["category_2"])

    parts = [x for x in (level1, level2) if x]

    return " > ".join(parts)


def read_source(shop):
    source = RAW_DIR / shop / "shop_data.dat"

    if not source.exists():
        raise FileNotFoundError(source)

    rows = []
    malformed = []

    # interaktiv.net legacy exports are Windows-1252 compatible.
    with source.open(
        "r",
        encoding="cp1252",
        errors="replace",
        newline=""
    ) as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\r\n")

            if not line:
                continue

            fields = line.split("|")

            if len(fields) != EXPECTED_FIELDS:
                malformed.append({
                    "source": shop,
                    "line_number": line_number,
                    "field_count": len(fields),
                    "expected": EXPECTED_FIELDS,
                })

            record = {
                "source": shop,
                "line_number": line_number,
                "row_id": field(fields, FIELD["row_id"]),
                "master_id": field(fields, FIELD["master_id"]),
                "sku": field(fields, FIELD["sku"]),
                "category_1": field(fields, FIELD["category_1"]),
                "category_2": field(fields, FIELD["category_2"]),
                "category_path": category_path(fields),
                "category_path_raw": field(
                    fields,
                    FIELD["category_path_raw"]
                ),
                "name": field(fields, FIELD["name"]),
                "price_raw": field(fields, FIELD["price"]),
                "price": normalize_price(
                    field(fields, FIELD["price"])
                ),
                "description": field(
                    fields,
                    FIELD["description"]
                ),
                "image": field(fields, FIELD["image"]),
                "manufacturer": field(
                    fields,
                    FIELD["manufacturer"]
                ),
                "seo_title": field(
                    fields,
                    FIELD["seo_title"]
                ),
                "ean": field(fields, FIELD["ean"]),
                "timestamps": field(
                    fields,
                    FIELD["timestamps"]
                ),
            }

            # Keep all 62 raw fields so no source information is lost.
            for number in range(1, EXPECTED_FIELDS + 1):
                record[f"raw_{number:02d}"] = field(
                    fields,
                    number
                )

            rows.append(record)

    return rows, malformed


def unique_nonempty(records, key):
    values = []

    for record in records:
        value = record.get(key, "").strip()

        if value and value not in values:
            values.append(value)

    return values


def first_nonempty(records, key):
    values = unique_nonempty(records, key)
    return values[0] if values else ""


def group_products(shop, rows):
    groups = defaultdict(list)

    for row in rows:
        master_id = row["master_id"]

        if not master_id:
            # Should not happen according to current analysis.
            master_id = f"missing:{row['row_id']}"

        groups[master_id].append(row)

    products = []
    conflicts = []

    conflict_fields = (
        "sku",
        "name",
        "price",
        "description",
        "image",
        "manufacturer",
        "ean",
    )

    for master_id, records in groups.items():
        categories = unique_nonempty(
            records,
            "category_path"
        )

        row_ids = unique_nonempty(
            records,
            "row_id"
        )

        for key in conflict_fields:
            values = unique_nonempty(records, key)

            if len(values) > 1:
                conflicts.append({
                    "source": shop,
                    "master_id": master_id,
                    "field": key,
                    "values": " || ".join(values),
                    "row_ids": " | ".join(row_ids),
                })

        products.append({
            "source": shop,
            "master_id": master_id,
            "sku": first_nonempty(records, "sku"),
            "name": first_nonempty(records, "name"),
            "price": first_nonempty(records, "price"),
            "price_raw": first_nonempty(
                records,
                "price_raw"
            ),
            "manufacturer": first_nonempty(
                records,
                "manufacturer"
            ),
            "ean": first_nonempty(records, "ean"),
            "image": first_nonempty(records, "image"),
            "description": first_nonempty(
                records,
                "description"
            ),
            "seo_title": first_nonempty(
                records,
                "seo_title"
            ),
            "categories": " || ".join(categories),
            "category_count": len(categories),
            "row_ids": " | ".join(row_ids),
            "source_row_count": len(records),
        })

    products.sort(
        key=lambda item: (
            item["sku"].lower(),
            item["master_id"]
        )
    )

    return products, conflicts


def write_csv(path, rows, fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)

    if fieldnames is None:
        if not rows:
            return
        fieldnames = list(rows[0].keys())

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


def sku_conflicts(shop, products):
    by_sku = defaultdict(list)

    for product in products:
        if product["sku"]:
            by_sku[product["sku"]].append(product)

    result = []

    for sku, records in by_sku.items():
        master_ids = sorted({
            record["master_id"]
            for record in records
        })

        if len(master_ids) <= 1:
            continue

        result.append({
            "source": shop,
            "sku": sku,
            "master_ids": " | ".join(master_ids),
            "product_count": len(master_ids),
            "names": " || ".join(
                unique_nonempty(records, "name")
            ),
            "eans": " || ".join(
                unique_nonempty(records, "ean")
            ),
        })

    return sorted(
        result,
        key=lambda item: item["sku"].lower()
    )


def main():
    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    summary = []

    for shop in SHOPS:
        rows, malformed = read_source(shop)
        products, conflicts = group_products(shop, rows)
        duplicated_skus = sku_conflicts(shop, products)

        write_csv(
            ROWS_DIR / f"{shop}.csv",
            rows
        )

        write_csv(
            PRODUCTS_DIR / f"{shop}.csv",
            products
        )

        write_csv(
            REPORTS_DIR / f"{shop}_conflicts.csv",
            conflicts,
            fieldnames=[
                "source",
                "master_id",
                "field",
                "values",
                "row_ids",
            ],
        )

        write_csv(
            REPORTS_DIR / f"{shop}_sku_conflicts.csv",
            duplicated_skus,
            fieldnames=[
                "source",
                "sku",
                "master_ids",
                "product_count",
                "names",
                "eans",
            ],
        )

        write_csv(
            REPORTS_DIR / f"{shop}_malformed.csv",
            malformed,
            fieldnames=[
                "source",
                "line_number",
                "field_count",
                "expected",
            ],
        )

        summary.append({
            "source": shop,
            "source_rows": len(rows),
            "master_products": len(products),
            "attribute_conflicts": len(conflicts),
            "sku_conflicts": len(duplicated_skus),
            "malformed_rows": len(malformed),
        })

        print()
        print(f"===== {shop.upper()} =====")
        print(f"Source rows:        {len(rows)}")
        print(f"Master products:    {len(products)}")
        print(f"Attribute conflicts:{len(conflicts):>5}")
        print(f"SKU conflicts:      {len(duplicated_skus):>5}")
        print(f"Malformed rows:     {len(malformed):>5}")

    write_csv(
        REPORTS_DIR / "summary.csv",
        summary
    )

    print()
    print("Done.")
    print(f"Output: {WORKING_DIR}")


if __name__ == "__main__":
    main()
