#!/usr/bin/env python3
"""OSM discovery connector — the deterministic front door of the pipeline.

Queries OpenStreetMap's Overpass API for businesses of a category in a
city (the same discovery idea as the real sales-machine's `osm` provider),
then feeds each candidate through the VERIFIED biz_add engine: scoring is
the program's deterministic formula, duplicates fail closed, and nothing
enters the pipeline without passing validation.

Usage:
    python examples/sales_app/discover_osm.py <token> <city> <category> [limit]

Categories map to OSM tags: cafe, restaurant, workshop, hotel, clinic...
"""

import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(ROOT))

OVERPASS = "https://overpass-api.de/api/interpreter"

# category -> (osm tag key, [values])
CATEGORIES = {
    "cafe": ("amenity", ["cafe"]),
    "restaurant": ("amenity", ["restaurant"]),
    "hotel": ("tourism", ["hotel", "guest_house"]),
    "clinic": ("amenity", ["clinic", "doctors"]),
    "pharmacy": ("amenity", ["pharmacy"]),
    "workshop": ("shop", ["car_repair"]),
    "bakery": ("shop", ["bakery"]),
    "gym": ("leisure", ["fitness_centre"]),
    "salon": ("shop", ["hairdresser", "beauty"]),
}


def discover(city: str, category: str, limit: int) -> list[dict]:
    if category not in CATEGORIES:
        raise SystemExit(f"unknown category {category!r}; "
                         f"have: {', '.join(sorted(CATEGORIES))}")
    tag, values = CATEGORIES[category]
    regex = "|".join(values)
    query = f"""
[out:json][timeout:25];
area["name"~"^{city}"]["boundary"="administrative"]->.a;
(
  nwr["{tag}"~"^({regex})$"](area.a);
);
out center tags {max(limit * 3, 30)};
"""
    data = urllib.parse.urlencode({"data": query}).encode()
    with urllib.request.urlopen(urllib.request.Request(
            OVERPASS, data=data, headers={"User-Agent": "2066-sales/1.0"}),
            timeout=40) as res:
        payload = json.loads(res.read())
    rows = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat", "")
        rows.append({"name": name,
                     "city": tags.get("addr:city", city),
                     "phone": tags.get("phone", tags.get("contact:phone", "")),
                     "website": tags.get("website",
                                         tags.get("contact:website", "")),
                     "lat": lat})
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    token, city, category = sys.argv[1], sys.argv[2], sys.argv[3]
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    from runtime import analyze, execute, parse_source  # noqa: E402
    from runtime.capabilities import GrantSet  # noqa: E402
    from runtime.data import DataPlane  # noqa: E402
    from runtime.session import SessionVerifier  # noqa: E402

    # same wiring as the server: this connector holds the db + grants,
    # the pipeline semantics stay inside the programs
    GRANTS = GrantSet.from_file(
        str(ROOT / "policies" / "deployment" / "sales-caps.json"))
    db_path = __import__("os").environ.get(
        "2066_SALES_DB", str(APP_DIR / "sales.db"))
    ident = json.loads((Path(__import__("os").environ.get(
        "2066_KEY_HOME", str(Path.home() / ".2066")))
        / "sales_server_identity.json").read_text(encoding="utf-8"))
    sessions = SessionVerifier(public_key=ident["public_key"])

    candidates = discover(city, category, limit)
    print(f"osm: {len(candidates)} candidates for {category!r} in {city!r}")
    added, skipped = 0, 0
    for c in candidates:
        program = parse_source(
            (ROOT / "programs" / "sales" / "business" / "add.ai")
            .read_text(encoding="utf-8"))
        analysis = analyze(program)
        db = DataPlane(db_path, program.entities, GRANTS, None)
        tier = 2 if c["website"] else 1
        stdin = io.StringIO("".join(
            x + "\n" for x in (token, c["name"], category, c["city"],
                               c["phone"], c["website"], str(tier))))
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin, io.StringIO()
        try:
            execute(program, analysis, grants=GRANTS, db=db,
                    sessions=sessions)
            result = sys.stdout.getvalue().strip()
        except Exception as exc:
            result = f"error {getattr(exc, 'code', 'E???')}"
        finally:
            sys.stdin, sys.stdout = old_in, old_out
            db.close()
        if result.startswith("ok:"):
            added += 1
            print(f"  + {c['name']} ({result})")
        else:
            skipped += 1
            print(f"  - {c['name']}: {result}")
    print(f"pipeline: {added} added, {skipped} rejected by the engines")


if __name__ == "__main__":
    main()
