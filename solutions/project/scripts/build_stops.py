"""Build data/stops.csv from data/stops_seed.csv.

For every seed row, look up the Wikipedia article, resolve redirects, and take
the canonical article URL and the Wikidata item. Coordinates come from Wikidata
(P625, CC0). Only facts and links are written: no article text.

Usage:
    python solutions/project/scripts/build_stops.py
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED_CSV = DATA_DIR / "stops_seed.csv"
TOURS_CSV = DATA_DIR / "tours.csv"
STOPS_CSV = DATA_DIR / "stops.csv"

USER_AGENT = "dtc-capstone-walking-tours/0.1 (course project)"
TIMEOUT_S = 30
BATCH = 40  # MediaWiki allows 50 titles per query
OUTPUT_FIELDS = (
    "id",
    "tour_id",
    "order",
    "name",
    "lat",
    "lon",
    "source_url",
    "wikidata_id",
    "personal_note",
)


@dataclass(frozen=True)
class Article:
    url: str
    wikidata_id: str


def get_json(url: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def fetch_articles(lang: str, titles: list[str]) -> dict[str, Article]:
    """Map each requested title to its canonical article, following redirects."""
    found: dict[str, Article] = {}
    for start in range(0, len(titles), BATCH):
        chunk = titles[start : start + BATCH]
        data = get_json(
            f"https://{lang}.wikipedia.org/w/api.php",
            {
                "action": "query",
                "format": "json",
                "redirects": "1",
                "prop": "info|pageprops",
                "inprop": "url",
                "ppprop": "wikibase_item",
                "titles": "|".join(chunk),
            },
        )["query"]
        aliases: dict[str, str] = {}
        for key in ("normalized", "redirects"):
            for hop in data.get(key, []):
                aliases[hop["to"]] = aliases.get(hop["from"], hop["from"])
        for page in data["pages"].values():
            if "missing" in page:
                continue
            requested = aliases.get(page["title"], page["title"])
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            found[requested] = Article(url=page["fullurl"], wikidata_id=qid)
    return found


def fetch_coordinates(qids: list[str]) -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    for start in range(0, len(qids), BATCH):
        chunk = qids[start : start + BATCH]
        entities = get_json(
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "format": "json",
                "props": "claims",
                "ids": "|".join(chunk),
            },
        )["entities"]
        for qid, entity in entities.items():
            claims = entity.get("claims", {}).get("P625", [])
            value = claims[0]["mainsnak"].get("datavalue", {}).get("value") if claims else None
            if value:
                coords[qid] = (round(value["latitude"], 6), round(value["longitude"], 6))
    return coords


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate_seed(seed: list[dict[str, str]], tour_ids: set[str]) -> list[str]:
    errors = []
    seen = set()
    for row in seed:
        if row["id"] in seen:
            errors.append(f"duplicate id {row['id']}")
        seen.add(row["id"])
        if row["tour_id"] not in tour_ids:
            errors.append(f"{row['id']}: unknown tour_id {row['tour_id']}")
    return errors


def build_rows(seed, articles, coords) -> tuple[list[dict[str, str]], list[str]]:
    rows, problems = [], []
    for row in seed:
        article = articles.get((row["wiki_lang"], row["wiki_title"]))
        if article is None:
            problems.append(f"{row['id']}: no article {row['wiki_lang']}:{row['wiki_title']}")
            continue
        lat, lon = coords.get(article.wikidata_id, ("", ""))
        if lat == "":
            problems.append(
                f"{row['id']}: no coordinates on {article.wikidata_id or 'missing item'}"
            )
        rows.append(
            {
                "id": row["id"],
                "tour_id": row["tour_id"],
                "order": row["order"],
                "name": row["name"],
                "lat": lat,
                "lon": lon,
                "source_url": article.url,
                "wikidata_id": article.wikidata_id,
                "personal_note": "",
            }
        )
    return rows, problems


def main() -> int:
    seed = read_csv(SEED_CSV)
    tour_ids = {tour["tour_id"] for tour in read_csv(TOURS_CSV)}
    errors = validate_seed(seed, tour_ids)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    articles: dict[tuple[str, str], Article] = {}
    for lang in sorted({row["wiki_lang"] for row in seed}):
        titles = [row["wiki_title"] for row in seed if row["wiki_lang"] == lang]
        for title, article in fetch_articles(lang, titles).items():
            articles[(lang, title)] = article

    qids = sorted({a.wikidata_id for a in articles.values() if a.wikidata_id})
    rows, problems = build_rows(seed, articles, fetch_coordinates(qids))

    with STOPS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} stops to {STOPS_CSV}")
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
