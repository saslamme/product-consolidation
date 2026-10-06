#!/usr/bin/env python3

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

SOURCE = (
    BASE
    / "raw"
    / "identbase"
    / "identbase_products.csv"
)

OUTPUT_DIR = (
    BASE
    / "working"
    / "identbase"
)

PRODUCTS_FILE = (
    OUTPUT_DIR
    / "products.csv"
)

TRANSLATIONS_FILE = (
    OUTPUT_DIR
    / "translations.csv"
)

REPORT_DIR = (
    OUTPUT_DIR
    / "reports"
)

TODAY = date.today()

EXPECTED_FIELDS = 89


def clean(value):
    return (value or "").strip()


def decimal_value(value):
    value = clean(value)

    if not value:
        return ""

    value = value.replace(",", ".")

    try:
        number = Decimal(value)

        return format(
            number.quantize(
                Decimal("0.01")
            ),
            "f"
        )

    except InvalidOperation:
        return value


def parse_date(value):
    value = clean(value)

    if not value:
        return None

    formats = (
        "%d.%m.%y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    )

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            ).date()
        except ValueError:
            continue

    return None


def format_date(value):
    if value is None:
        return ""

    return value.isoformat()


def parse_additional_attributes(value):
    """
    Parse Magento additional_attributes.

    Split only at commas followed by another
    attribute key, so commas inside values are
    not blindly destroyed.
    """

    value = clean(value)

    if not value:
        return {}

    pattern = re.compile(
        r'(?:^|,)([A-Za-z0-9_]+)='
    )

    matches = list(
        pattern.finditer(value)
    )

    result = {}

    for index, match in enumerate(matches):
        key = match.group(1)

        start = match.end()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(value)

        attribute_value = (
            value[start:end]
            .strip()
            .strip(",")
            .strip()
        )

        result[key] = attribute_value

    return result


def normalize_categories(value):
    value = clean(value)

    if not value:
        return []

    categories = []

    for item in value.split(","):
        item = item.strip()

        prefix = "Default Category/"

        if item.startswith(prefix):
            item = item[len(prefix):]

        item = item.strip("/ ")

        if item and item not in categories:
            categories.append(item)

    return categories


def calculate_effective_price(row):
    regular = decimal_value(
        row.get("price", "")
    )

    special = decimal_value(
        row.get("special_price", "")
    )

    if not special:
        return regular, False

    start = parse_date(
        row.get(
            "special_price_from_date",
            ""
        )
    )

    end = parse_date(
        row.get(
            "special_price_to_date",
            ""
        )
    )

    active = True

    if start and TODAY < start:
        active = False

    if end and TODAY > end:
        active = False

    if active:
        return special, True

    return regular, False


def load_rows():
    rows = []
    malformed = []

    with SOURCE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as handle:

        reader = csv.DictReader(
            handle,
            delimiter=",",
            quotechar='"'
        )

        if len(reader.fieldnames or []) != EXPECTED_FIELDS:
            raise RuntimeError(
                "Unexpected Magento column count: "
                f"{len(reader.fieldnames or [])} "
                f"(expected {EXPECTED_FIELDS})"
            )

        for logical_row, row in enumerate(
            reader,
            start=2
        ):
            if None in row:
                malformed.append({
                    "logical_row": logical_row,
                    "reason": "extra_columns",
                })
                continue

            rows.append(row)

    return rows, malformed


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


def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    rows, malformed = load_rows()

    by_sku = defaultdict(list)

    for row in rows:
        sku = clean(
            row.get("sku", "")
        )

        by_sku[sku].append(row)

    products = []
    translations = []

    default_conflicts = []
    missing_default = []

    store_counts = Counter()
    type_counts = Counter()

    for sku, sku_rows in sorted(
        by_sku.items()
    ):
        default_rows = [
            row
            for row in sku_rows
            if not clean(
                row.get(
                    "store_view_code",
                    ""
                )
            )
        ]

        if len(default_rows) == 0:
            missing_default.append({
                "sku": sku,
                "rows": len(sku_rows),
            })
            continue

        if len(default_rows) > 1:
            default_conflicts.append({
                "sku": sku,
                "default_rows": len(
                    default_rows
                ),
            })

        base = default_rows[0]

        attributes = (
            parse_additional_attributes(
                base.get(
                    "additional_attributes",
                    ""
                )
            )
        )

        manufacturer = (
            clean(
                attributes.get(
                    "manufacturer",
                    ""
                )
            )
            or clean(
                attributes.get(
                    "hersteller",
                    ""
                )
            )
        )

        mpn = clean(
            attributes.get(
                "mpn",
                ""
            )
        )

        categories = (
            normalize_categories(
                base.get(
                    "categories",
                    ""
                )
            )
        )

        effective_price, special_active = (
            calculate_effective_price(
                base
            )
        )

        special_from = parse_date(
            base.get(
                "special_price_from_date",
                ""
            )
        )

        special_to = parse_date(
            base.get(
                "special_price_to_date",
                ""
            )
        )

        product = {
            "source": "identbase",
            "source_key": (
                f"identbase:{sku}"
            ),

            "sku": sku,

            "product_type": clean(
                base.get(
                    "product_type",
                    ""
                )
            ),

            "attribute_set_code": clean(
                base.get(
                    "attribute_set_code",
                    ""
                )
            ),

            "name_de": clean(
                base.get(
                    "name",
                    ""
                )
            ),

            "description_de": clean(
                base.get(
                    "description",
                    ""
                )
            ),

            "short_description_de": clean(
                base.get(
                    "short_description",
                    ""
                )
            ),

            "manufacturer": manufacturer,
            "mpn": mpn,

            # No dedicated EAN/GTIN attribute
            # was found in the current export.
            "ean": "",

            "price": decimal_value(
                base.get(
                    "price",
                    ""
                )
            ),

            "special_price": decimal_value(
                base.get(
                    "special_price",
                    ""
                )
            ),

            "special_price_from": (
                format_date(
                    special_from
                )
            ),

            "special_price_to": (
                format_date(
                    special_to
                )
            ),

            "special_price_active": (
                "1"
                if special_active
                else "0"
            ),

            "effective_price": (
                effective_price
            ),

            "product_online": clean(
                base.get(
                    "product_online",
                    ""
                )
            ),

            "visibility": clean(
                base.get(
                    "visibility",
                    ""
                )
            ),

            "qty": decimal_value(
                base.get(
                    "qty",
                    ""
                )
            ),

            "is_in_stock": clean(
                base.get(
                    "is_in_stock",
                    ""
                )
            ),

            "categories": (
                " || ".join(
                    categories
                )
            ),

            "category_count": len(
                categories
            ),

            "base_image": clean(
                base.get(
                    "base_image",
                    ""
                )
            ),

            "additional_images": clean(
                base.get(
                    "additional_images",
                    ""
                )
            ),

            "url_key": clean(
                base.get(
                    "url_key",
                    ""
                )
            ),

            "meta_title": clean(
                base.get(
                    "meta_title",
                    ""
                )
            ),

            "meta_description": clean(
                base.get(
                    "meta_description",
                    ""
                )
            ),

            "related_skus": clean(
                base.get(
                    "related_skus",
                    ""
                )
            ),

            "crosssell_skus": clean(
                base.get(
                    "crosssell_skus",
                    ""
                )
            ),

            "upsell_skus": clean(
                base.get(
                    "upsell_skus",
                    ""
                )
            ),

            "associated_skus": clean(
                base.get(
                    "associated_skus",
                    ""
                )
            ),

            "configurable_variations": clean(
                base.get(
                    "configurable_variations",
                    ""
                )
            ),

            "configurable_variation_labels": clean(
                base.get(
                    "configurable_variation_labels",
                    ""
                )
            ),

            "additional_attributes_json": (
                json.dumps(
                    attributes,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
        }

        #
        # Add translations.
        #
        for row in sku_rows:
            store = clean(
                row.get(
                    "store_view_code",
                    ""
                )
            )

            store_counts[
                store or "[DEFAULT]"
            ] += 1

            type_counts[
                clean(
                    row.get(
                        "product_type",
                        ""
                    )
                )
            ] += 1

            if not store:
                continue

            translations.append({
                "sku": sku,
                "store_view_code": store,
                "name": clean(
                    row.get(
                        "name",
                        ""
                    )
                ),
                "description": clean(
                    row.get(
                        "description",
                        ""
                    )
                ),
                "short_description": clean(
                    row.get(
                        "short_description",
                        ""
                    )
                ),
                "url_key": clean(
                    row.get(
                        "url_key",
                        ""
                    )
                ),
                "meta_title": clean(
                    row.get(
                        "meta_title",
                        ""
                    )
                ),
                "meta_description": clean(
                    row.get(
                        "meta_description",
                        ""
                    )
                ),
            })

            #
            # Also expose common languages
            # directly on the product row.
            #
            if store in {
                "en",
                "fr",
                "es",
                "de",
            }:
                product[
                    f"name_{store}"
                ] = clean(
                    row.get(
                        "name",
                        ""
                    )
                )

                product[
                    f"description_{store}"
                ] = clean(
                    row.get(
                        "description",
                        ""
                    )
                )

                product[
                    f"short_description_{store}"
                ] = clean(
                    row.get(
                        "short_description",
                        ""
                    )
                )

        products.append(product)

    #
    # Make all product columns consistent.
    #
    product_fields = [
        "source",
        "source_key",
        "sku",
        "product_type",
        "attribute_set_code",

        "name_de",
        "name_en",
        "name_fr",
        "name_es",

        "description_de",
        "description_en",
        "description_fr",
        "description_es",

        "short_description_de",
        "short_description_en",
        "short_description_fr",
        "short_description_es",

        "manufacturer",
        "mpn",
        "ean",

        "price",
        "special_price",
        "special_price_from",
        "special_price_to",
        "special_price_active",
        "effective_price",

        "product_online",
        "visibility",

        "qty",
        "is_in_stock",

        "categories",
        "category_count",

        "base_image",
        "additional_images",

        "url_key",
        "meta_title",
        "meta_description",

        "related_skus",
        "crosssell_skus",
        "upsell_skus",
        "associated_skus",

        "configurable_variations",
        "configurable_variation_labels",

        "additional_attributes_json",
    ]

    for product in products:
        for field in product_fields:
            product.setdefault(
                field,
                ""
            )

    write_csv(
        PRODUCTS_FILE,
        products,
        product_fields,
    )

    write_csv(
        TRANSLATIONS_FILE,
        translations,
    )

    write_csv(
        REPORT_DIR
        / "malformed.csv",
        malformed,
        [
            "logical_row",
            "reason",
        ],
    )

    write_csv(
        REPORT_DIR
        / "default_conflicts.csv",
        default_conflicts,
        [
            "sku",
            "default_rows",
        ],
    )

    write_csv(
        REPORT_DIR
        / "missing_default.csv",
        missing_default,
        [
            "sku",
            "rows",
        ],
    )

    price_count = sum(
        1
        for p in products
        if p["price"]
    )

    effective_price_count = sum(
        1
        for p in products
        if p["effective_price"]
    )

    special_count = sum(
        1
        for p in products
        if p["special_price"]
    )

    active_special_count = sum(
        1
        for p in products
        if p["special_price_active"] == "1"
    )

    manufacturer_count = sum(
        1
        for p in products
        if p["manufacturer"]
    )

    mpn_count = sum(
        1
        for p in products
        if p["mpn"]
    )

    image_count = sum(
        1
        for p in products
        if p["base_image"]
    )

    online_count = sum(
        1
        for p in products
        if p["product_online"] == "1"
    )

    print()
    print(
        "===== IDENTBASE PARSE ====="
    )

    print(
        f"Magento source rows:       "
        f"{len(rows)}"
    )

    print(
        f"Products / SKUs:           "
        f"{len(products)}"
    )

    print(
        f"Translations:              "
        f"{len(translations)}"
    )

    print(
        f"Malformed rows:            "
        f"{len(malformed)}"
    )

    print(
        f"Missing default rows:      "
        f"{len(missing_default)}"
    )

    print(
        f"Multiple default rows:     "
        f"{len(default_conflicts)}"
    )

    print()

    print(
        f"Products with price:       "
        f"{price_count}"
    )

    print(
        f"Products effective price:  "
        f"{effective_price_count}"
    )

    print(
        f"Products special price:    "
        f"{special_count}"
    )

    print(
        f"Active special prices:     "
        f"{active_special_count}"
    )

    print()

    print(
        f"Products manufacturer:     "
        f"{manufacturer_count}"
    )

    print(
        f"Products MPN:              "
        f"{mpn_count}"
    )

    print(
        f"Products base image:       "
        f"{image_count}"
    )

    print(
        f"Products online:           "
        f"{online_count}"
    )

    print()
    print("Store views:")

    for store, count in (
        store_counts.most_common()
    ):
        print(
            f"  {store:10} {count}"
        )

    print()
    print("Output:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
