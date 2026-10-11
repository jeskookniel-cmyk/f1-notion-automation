# F1 HUB — Automated Standings for Notion

A Python + GitHub Actions integration that syncs Formula 1 driver and constructor standings from the public [Jolpica-F1 API](https://github.com/jolpica/jolpica-f1) into Notion.

## What it does

- Creates four Notion databases: **Driver Standings**, **Constructor Standings**, **Driver Standings Snapshots**, and **Constructor Standings Snapshots**.
- Supports multiple seasons via `F1_SEASONS` (default `2024,2025,2026`).
- Stores current season/competitor rows and historical round-by-round standings.
- Uses stable `Key` values and updates existing pages, so repeat runs do not create duplicate records.
- Runs daily via GitHub Actions and supports a manual **Run workflow** trigger.
- Does not require a Jolpica API key. Do not commit Notion tokens or `.env` files.

> Accuracy note: a race is considered completed when its scheduled date is on or before the runner's current date. For each such round, the script asks Jolpica for the standings at that round. Check the resulting data after the first run, especially during a race weekend or if a race is postponed.

## 1. Create a Notion integration

1. Open [Notion integrations](https://www.notion.so/profile/integrations) and create an **internal integration**.
2. Copy its secret token. Treat it like a password.
3. In Notion, create a normal page called `F1 HUB — Standings` (this is the parent page).
4. Open the page's `•••` menu or `Share` menu, invite your integration, and grant edit access.
5. Copy the parent page ID from the page URL. It is the 32-character ID in the URL; hyphens are okay.

## 2. Create the databases

Python 3.11+ is recommended.

### Windows PowerShell

```powershell
cd f1-notion-automation
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:NOTION_TOKEN = "secret_your_token"
$env:NOTION_PARENT_PAGE_ID = "your_parent_page_id"
python setup_notion.py
```

### macOS / Linux

```bash
cd f1-notion-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export NOTION_TOKEN='secret_your_token'
export NOTION_PARENT_PAGE_ID='your_parent_page_id'
python setup_notion.py
```

The setup script prints four database IDs. Save them; the sync script needs all four. Run `setup_notion.py` only once, or it will create another set of databases.

## 3. Test locally

Set the environment variables printed by setup:

```bash
# PowerShell example
$env:NOTION_DB_DRIVER_STANDINGS = "database_id_from_setup"
$env:NOTION_DB_CONSTRUCTOR_STANDINGS = "database_id_from_setup"
$env:NOTION_DB_DRIVER_STANDINGS_SNAPSHOTS = "database_id_from_setup"
$env:NOTION_DB_CONSTRUCTOR_STANDINGS_SNAPSHOTS = "database_id_from_setup"
$env:F1_SEASONS = "2024,2025,2026"
python f1_notion_sync.py
```

The four database ID values are different; don't paste the same ID into every variable. For repeat local runs, you can use a `.env` file only if you also load it yourself; the script intentionally does not auto-load `.env`.

## 4. Put the project on GitHub

1. Create a private GitHub repository, e.g. `f1-notion-standings`.
2. Upload all files in this project, preserving `.github/workflows/f1-standings.yml`.
3. In GitHub, open **Settings → Secrets and variables → Actions**.
4. Under **Repository secrets**, add:
   - `NOTION_TOKEN`
   - `NOTION_PARENT_PAGE_ID`
   - `NOTION_DB_DRIVER_STANDINGS`
   - `NOTION_DB_CONSTRUCTOR_STANDINGS`
   - `NOTION_DB_DRIVER_STANDINGS_SNAPSHOTS`
   - `NOTION_DB_CONSTRUCTOR_STANDINGS_SNAPSHOTS`
5. Under **Repository variables**, add:
   - `F1_SEASONS` = `2024,2025,2026` (or the seasons you want)
   - `NOTION_VERSION` = `2022-06-28`
6. Open **Actions → F1 Standings to Notion → Run workflow** for the first test. Review the run logs and all four Notion databases.

GitHub Actions scheduled workflows run from the default branch. The workflow runs daily at 03:20 UTC (11:20 a.m. Malaysia time). GitHub may delay scheduled jobs during high load. Manual trigger is available in the Actions tab.

## 5. Updating seasons

Edit the `F1_SEASONS` repository variable, e.g. `2022,2023,2024,2025,2026`. Existing rows are updated by stable key; missing rows are created. Historical snapshots are stored by season + round + driver/constructor ID.

## Troubleshooting

- **401/unauthorized from Notion:** verify `NOTION_TOKEN`; make sure it is the integration's internal token.
- **403/capability error:** share the parent page with the integration and grant edit access. The integration needs access to all databases it creates under that page.
- **Database IDs missing:** verify all four `NOTION_DB_...` variables exactly match the setup script output.
- **No rows created:** ensure `F1_SEASONS` contains valid years and the API returns standings for those years.
- **Duplicate databases:** don't rerun `setup_notion.py`; it creates new databases each time.
- **No duplicates in sync tables:** the script matches the exact `Key` rich-text value before creating a page. Avoid manually editing Key values.

## API references

- [Jolpica-F1 docs](https://github.com/jolpica/jolpica-f1/blob/main/docs/README.md)
- [Jolpica races endpoint](https://github.com/jolpica/jolpica-f1/blob/main/docs/endpoints/races.md)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions)
