"""Create the Notion databases required by the F1 standings sync."""
import os
import sys
import requests

BASE = "https://api.notion.com/v1"
TOKEN = os.getenv("NOTION_TOKEN", "").strip()
PARENT = os.getenv("NOTION_PARENT_PAGE_ID", "").strip().replace("-", "")
VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip()

if not TOKEN or not PARENT or "replace_with" in PARENT:
    sys.exit("Set NOTION_TOKEN and NOTION_PARENT_PAGE_ID in your environment first.")

S = requests.Session()
S.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": VERSION,
    "Content-Type": "application/json",
})


def api(method, path, **kwargs):
    r = S.request(method, f"{BASE}{path}", timeout=30, **kwargs)
    if not r.ok:
        raise RuntimeError(f"Notion API {method} {path} failed ({r.status_code}): {r.text}")
    return r.json() if r.text else {}


def title(text):
    return [{"type": "text", "text": {"content": text}}]


def create_db(name, props):
    data = api("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": PARENT},
        "title": title(name),
        "properties": props,
    })
    print(f"Created: {name} -> {data['id']}")
    return data["id"]


def schema(kind):
    # Keep Key as a normal rich_text field. The sync script enforces uniqueness by querying it.
    p = {
        "Name": {"title": {}},
        "Key": {"rich_text": {}},
        "Season": {"number": {"format": "number"}},
        "Round": {"number": {"format": "number"}},
        "Position": {"number": {"format": "number"}},
        "Points": {"number": {"format": "number"}},
        "Wins": {"number": {"format": "number"}},
        "Updated At": {"date": {}},
        "Source URL": {"url": {}},
    }
    if kind.startswith("Driver"):
        p["Driver ID"] = {"rich_text": {}}
        p["Driver Code"] = {"rich_text": {}}
        p["Driver"] = {"rich_text": {}}
        p["Constructor"] = {"rich_text": {}}
    else:
        p["Constructor ID"] = {"rich_text": {}}
        p["Constructor"] = {"rich_text": {}}
    if kind.endswith("Snapshots"):
        p["Snapshot Date"] = {"date": {}}
    return p


# Run once. If a database already exists, do not run this again unless you intend to create duplicates.
ids = {}
for name in ("Driver Standings", "Constructor Standings", "Driver Standings Snapshots", "Constructor Standings Snapshots"):
    ids[name] = create_db(name, schema(name))

print("\nAdd these as GitHub repository secrets (or put them in .env for local testing):")
for name, value in ids.items():
    env_name = "NOTION_DB_" + name.upper().replace(" ", "_")
    print(f"{env_name}={value}")
