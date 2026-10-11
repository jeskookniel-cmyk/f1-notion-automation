"""Sync multi-season Formula 1 driver/constructor standings to Notion.

Uses the public Jolpica-F1 Ergast-compatible API. Re-running is idempotent: each row
is identified by a stable Key property and existing Notion pages are updated in place.
"""
from __future__ import annotations
import os
import sys
import time
from datetime import date, datetime, timezone
from typing import Any
import requests

JOLPICA = "https://api.jolpi.ca/ergast/f1"
NOTION = "https://api.notion.com/v1"
VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip() or "2022-06-28"
TOKEN = os.getenv("NOTION_TOKEN", "").strip()
DBS = {
    "drivers": os.getenv("NOTION_DB_DRIVER_STANDINGS", "").strip(),
    "constructors": os.getenv("NOTION_DB_CONSTRUCTOR_STANDINGS", "").strip(),
    "driver_snapshots": os.getenv("NOTION_DB_DRIVER_STANDINGS_SNAPSHOTS", "").strip(),
    "constructor_snapshots": os.getenv("NOTION_DB_CONSTRUCTOR_STANDINGS_SNAPSHOTS", "").strip(),
}
SEASONS = [x.strip() for x in (os.getenv("F1_SEASONS") or "2024,2025,2026").split(",") if x.strip()]
TODAY = date.today()

if not TOKEN:
    sys.exit("Missing NOTION_TOKEN.")
missing = [k for k, v in DBS.items() if not v]
if missing:
    sys.exit("Missing Notion database IDs: " + ", ".join(missing) + ". Run setup_notion.py and set the printed IDs as environment variables.")

api = requests.Session()
api.headers.update({"User-Agent": "F1NotionStandings/1.0 (Jolpica API client)"})
notion = requests.Session()
notion.headers.update({"Authorization": f"Bearer {TOKEN}", "Notion-Version": VERSION, "Content-Type": "application/json"})


def request_json(session: requests.Session, method: str, url: str, **kwargs) -> dict[str, Any]:
    last = None
    for attempt in range(5):
        try:
            r = session.request(method, url, timeout=40, **kwargs)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
                time.sleep(min(2 ** attempt, 16))
                continue
            if not r.ok:
                raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:1000]}")
            return r.json() if r.text else {}
        except requests.RequestException as exc:
            last = exc
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"Request failed after retries: {url}: {last}")


def jolpica(path: str) -> dict[str, Any]:
    return request_json(api, "GET", f"{JOLPICA}/{path.lstrip('/')}" + ("" if path.endswith(".json") else ".json"), params={"limit": 100})


def mrdata(data):
    return data.get("MRData", {})


def races_for_season(season: str) -> list[dict]:
    d = jolpica(f"{season}/races")
    return mrdata(d).get("RaceTable", {}).get("Races", [])


def standings_for_round(season: str, round_no: int, kind: str) -> list[dict]:
    endpoint = "driverstandings" if kind == "drivers" else "constructorstandings"
    d = jolpica(f"{season}/{round_no}/{endpoint}")
    table = mrdata(d).get("StandingsTable", {}).get("StandingsLists", [])
    if not table:
        return []
    key = "DriverStandings" if kind == "drivers" else "ConstructorStandings"
    return table[0].get(key, [])


def current_standings(season: str, kind: str, last_round: int | None) -> list[dict]:
    if last_round is None:
        return []
    return standings_for_round(season, last_round, kind)


def rt(value: str) -> list[dict]:
    return [{"type": "text", "text": {"content": str(value)[:2000]}}]


def prop_text(value: str) -> dict:
    return {"rich_text": rt(value)}


def prop_number(value) -> dict:
    try:
        return {"number": float(value)}
    except (TypeError, ValueError):
        return {"number": None}


def page_properties(row: dict, snapshot: bool) -> dict:
    kind = row["kind"]
    props = {
        "Name": {"title": rt(row["name"])},
        "Key": prop_text(row["key"]),
        "Season": prop_number(row["season"]),
        "Round": prop_number(row["round"]),
        "Position": prop_number(row["position"]),
        "Points": prop_number(row["points"]),
        "Wins": prop_number(row["wins"]),
        "Updated At": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        "Source URL": {"url": row.get("source_url") or None},
    }
    if kind == "drivers":
        props.update({
            "Driver ID": prop_text(row.get("driver_id", "")),
            "Driver Code": prop_text(row.get("driver_code", "")),
            "Driver": prop_text(row.get("driver", "")),
            "Constructor": prop_text(row.get("constructor", "")),
        })
    else:
        props.update({
            "Constructor ID": prop_text(row.get("constructor_id", "")),
            "Constructor": prop_text(row.get("constructor", "")),
        })
    if snapshot:
        props["Snapshot Date"] = {"date": {"start": row["snapshot_date"]}}
    return props


INDEX: dict[str, dict[str, str]] = {}

def load_database_index(db_id: str) -> dict[str, str]:
    """Read existing Key -> page ID pairs once per database, with pagination."""
    result: dict[str, str] = {}
    cursor = None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = request_json(notion, "POST", f"{NOTION}/databases/{db_id}/query", json=body)
        for page in data.get("results", []):
            key_prop = page.get("properties", {}).get("Key", {}).get("rich_text", [])
            key = "".join(part.get("plain_text", part.get("text", {}).get("content", "")) for part in key_prop)
            if key:
                result[key] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    print(f"Loaded {len(result)} existing keys from database {db_id}")
    return result


def upsert(db_id: str, row: dict, snapshot: bool) -> str:
    props = page_properties(row, snapshot)
    index = INDEX[db_id]
    existing = index.get(row["key"])
    if existing:
        request_json(notion, "PATCH", f"{NOTION}/pages/{existing}", json={"properties": props})
        return "updated"
    created = request_json(notion, "POST", f"{NOTION}/pages", json={
        "parent": {"database_id": db_id},
        "properties": props,
    })
    index[row["key"]] = created["id"]
    return "created"


def driver_rows(standings: list[dict], season: str, round_no: int, snapshot: bool, race_name: str, snapshot_date: str) -> list[dict]:
    rows = []
    for item in standings:
        driver = item.get("Driver", {})
        constructors = item.get("Constructors", [])
        constructor = constructors[-1] if constructors else {}
        driver_id = driver.get("driverId", "unknown")
        driver_name = " ".join(x for x in [driver.get("givenName", ""), driver.get("familyName", "")] if x).strip() or driver_id
        row_round = int(round_no)
        label = f"{season} R{row_round:02d} · {driver_name}" if snapshot else f"{season} · {driver_name}"
        key = f"{season}:{row_round}:{driver_id}" if snapshot else f"{season}:{driver_id}"
        rows.append({"kind": "drivers", "name": label, "key": key, "season": season, "round": row_round,
            "position": item.get("position", ""), "points": item.get("points", 0), "wins": item.get("wins", 0),
            "driver_id": driver_id, "driver_code": driver.get("code", ""), "driver": driver_name,
            "constructor": constructor.get("name", ""), "source_url": driver.get("url", ""), "snapshot_date": snapshot_date})
    return rows


def constructor_rows(standings: list[dict], season: str, round_no: int, snapshot: bool, snapshot_date: str) -> list[dict]:
    rows = []
    for item in standings:
        constructor = item.get("Constructor", {})
        constructor_id = constructor.get("constructorId", "unknown")
        name = constructor.get("name", constructor_id)
        key = f"{season}:{int(round_no)}:{constructor_id}" if snapshot else f"{season}:{constructor_id}"
        rows.append({"kind": "constructors", "name": f"{season} R{int(round_no):02d} · {name}" if snapshot else f"{season} · {name}",
            "key": key, "season": season, "round": int(round_no), "position": item.get("position", ""),
            "points": item.get("points", 0), "wins": item.get("wins", 0), "constructor_id": constructor_id,
            "constructor": name, "source_url": constructor.get("url", ""), "snapshot_date": snapshot_date})
    return rows


def sync_rows(db_id: str, rows: list[dict], snapshot: bool) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        result = upsert(db_id, row, snapshot)
        if result == "created": created += 1
        else: updated += 1
        time.sleep(0.12)  # Be gentle to both public APIs.
    return created, updated


def main():
    for db_id in DBS.values():
        INDEX[db_id] = load_database_index(db_id)
    totals = {"created": 0, "updated": 0, "snapshots": 0}
    for season in SEASONS:
        print(f"\n=== Season {season} ===")
        races = races_for_season(season)
        completed = []
        for race in races:
            race_date = race.get("date", "")
            try:
                round_no = int(race.get("round", 0))
                if race_date and date.fromisoformat(race_date) <= TODAY:
                    completed.append((round_no, race))
            except (ValueError, TypeError):
                continue
        if not completed:
            print(f"No races dated on or before {TODAY} for {season}; skipping.")
            continue
        completed.sort(key=lambda x: x[0])
        last_round, last_race = completed[-1]
        last_date = last_race.get("date", str(TODAY))
        print(f"Rounds considered completed by date: {len(completed)}; latest R{last_round} {last_race.get('raceName', '')} ({last_date})")

        # Current tables: stable key per season + competitor; updated in place each run.
        for kind, db_key in (("drivers", "drivers"), ("constructors", "constructors")):
            standings = current_standings(season, kind, last_round)
            if not standings:
                print(f"No {kind} standings returned for {season} round {last_round}; skipping current table.")
                continue
            rows = driver_rows(standings, season, last_round, False, last_race.get("raceName", ""), last_date) if kind == "drivers" else constructor_rows(standings, season, last_round, False, last_date)
            c, u = sync_rows(DBS[db_key], rows, False)
            totals["created"] += c; totals["updated"] += u
            print(f"{kind} current: {c} created, {u} updated")

        # Historical tables: one record per competitor per season-round, upserted idempotently.
        for round_no, race in completed:
            snapshot_date = race.get("date", last_date)
            for kind, db_key in (("drivers", "driver_snapshots"), ("constructors", "constructor_snapshots")):
                standings = standings_for_round(season, round_no, kind)
                if not standings:
                    print(f"No {kind} snapshot data at {season} R{round_no}; skipping.")
                    continue
                rows = driver_rows(standings, season, round_no, True, race.get("raceName", ""), snapshot_date) if kind == "drivers" else constructor_rows(standings, season, round_no, True, snapshot_date)
                c, u = sync_rows(DBS[db_key], rows, True)
                totals["created"] += c; totals["updated"] += u
                totals["snapshots"] += len(rows)
            time.sleep(0.2)
    print("\n=== Sync complete ===")
    print(f"Created: {totals['created']} | Updated: {totals['updated']} | Snapshot rows processed: {totals['snapshots']}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
