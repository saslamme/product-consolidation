#!/usr/bin/env python3

import csv
import re
from collections import defaultdict
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent

IDB_FILE = BASE / "working/identbase/products.csv"

INT_FILE = (
    BASE
    / "working/interaktiv/merged/"
    / "interaktiv_master_products.csv"
)

OUT = (
    BASE
    / "working/identbase_matching/"
    / "image_matches.csv"
)


def norm_image(value):
    value = (value or "").strip().lower()

    if not value:
        return ""

    value = value.replace("\\", "/")
    value = value.rsplit("/", 1)[-1]

    # extension entfernen
    value = re.sub(
        r"\.(jpg|jpeg|png|gif|webp|tif|tiff)$",
        "",
        value,
        flags=re.I
    )

    # typische Separatoren vereinheitlichen
    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )

    return value


identbase = []

with IDB_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    for row in csv.DictReader(f):
        image = norm_image(
            row["base_image"]
        )

        if image:
            identbase.append({
                "sku": row["sku"],
                "mpn": row["mpn"],
                "name": row["name_de"],
                "manufacturer": row["manufacturer"],
                "image": row["base_image"],
                "image_norm": image,
            })


interaktiv = []

with INT_FILE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    for row in csv.DictReader(f):

        images = set()

        for shop in (
            "identible",
            "cardnext",
            "inplastor",
        ):
            image = row.get(
                f"{shop}_image",
                ""
            )

            normalized = norm_image(
                image
            )

            if normalized:
                images.add(
                    normalized
                )

        for image in images:
            interaktiv.append({
                "group_id": row[
                    "interaktiv_group_id"
                ],
                "reference_sku": row[
                    "reference_sku"
                ],
                "reference_name": row[
                    "reference_name"
                ],
                "reference_manufacturer": row[
                    "reference_manufacturer"
                ],
                "image_norm": image,
            })


idb_index = defaultdict(list)
int_index = defaultdict(list)

for row in identbase:
    idb_index[row["image_norm"]].append(
        row
    )

for row in interaktiv:
    int_index[row["image_norm"]].append(
        row
    )


matches = []

for image in sorted(
    set(idb_index)
    & set(int_index)
):

    idb_rows = idb_index[image]
    int_rows = int_index[image]

    for a in idb_rows:
        for b in int_rows:

            matches.append({
                "image_norm": image,
                "identbase_sku": a["sku"],
                "identbase_mpn": a["mpn"],
                "identbase_name": a["name"],
                "identbase_manufacturer": a[
                    "manufacturer"
                ],
                "identbase_image": a["image"],
                "interaktiv_group_id": b[
                    "group_id"
                ],
                "interaktiv_sku": b[
                    "reference_sku"
                ],
                "interaktiv_name": b[
                    "reference_name"
                ],
                "interaktiv_manufacturer": b[
                    "reference_manufacturer"
                ],
                "identbase_image_count": len(
                    idb_rows
                ),
                "interaktiv_image_count": len(
                    int_rows
                ),
            })


OUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

fields = [
    "image_norm",
    "identbase_sku",
    "identbase_mpn",
    "identbase_name",
    "identbase_manufacturer",
    "identbase_image",
    "interaktiv_group_id",
    "interaktiv_sku",
    "interaktiv_name",
    "interaktiv_manufacturer",
    "identbase_image_count",
    "interaktiv_image_count",
]

with OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(matches)


unique = [
    r for r in matches
    if (
        r["identbase_image_count"] == 1
        and
        r["interaktiv_image_count"] == 1
    )
]

print(
    "Identbase mit Bild:",
    len(identbase)
)

print(
    "Interaktiv Bildreferenzen:",
    len(interaktiv)
)

print(
    "Bild-Match-Paare:",
    len(matches)
)

print(
    "Eindeutige 1:1 Bildmatches:",
    len(unique)
)

print()
print("Output:")
print(OUT)
