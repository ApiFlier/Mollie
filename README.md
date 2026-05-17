# Event Map

A self-hosted event discovery map for regional farms, farmers markets, festivals, and local destinations. Displays 180+ locations on a hybrid aerial/satellite map with filtering by category, month, crop, and growing practices.

---

## Quick Start
### 1. Install Docker
**Linux** — [Docker Engine](https://docs.docker.com/engine/install/) + Docker Compose plugin:
```bash
# Example for Ubuntu/Debian
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Verify Docker

```bash
docker --version
docker compose version
```

Both commands must succeed before proceeding.

### 3. Clone, configure, and run
```bash
git clone https://github.com/ApiFlier/event-map.git event-map
cd event-map
chmod +x setup.sh
./setup.sh
```

`setup.sh` will:
- Generate `.env` automatically with random passwords and secrets
- Create a default admin account (`meeks` / `meeks`) — **change the password at first login**
- Find an available host port automatically (starting at 8090)
- Build and start the Docker containers
- Create or reuse a persistent Docker-managed database volume (`event_map_db_data`)
- Detect available backups and ask which to restore (repo baseline, local backup, or fresh)
- Print the local URL when done

No external API keys required.

---

## Common commands

| Command | Purpose |
|---------|---------|
| `./setup.sh` | First-time setup — builds containers, generates secrets, loads seed data |
| `./update.sh` | Pull latest code and rebuild the app container |
| `./update-seed.sh` | Refresh `api/data/seed.sql` from the current curated database |

---

## Updating the app

Normal update workflow:

```bash
./update.sh
```

`update.sh` handles everything: it runs `git pull --ff-only`, rebuilds the app container, waits for the health endpoint, and prints the Events, Map, and Admin URLs.

**What `update.sh` does:**
- Checks for uncommitted local changes — stops with a clear message if any exist
- Runs `git pull --ff-only` (stops on failure; does not merge or auto-resolve)
- Rebuilds the Docker image from the updated source
- Recreates the `event-map-app` container
- Waits for the health endpoint to respond
- Prints the Events, Map, and Admin URLs

**What `update.sh` does not do:**
- Does not run `git pull` if the working tree is dirty — commit or stash changes first
- Does not auto-stash, auto-commit, or auto-resolve conflicts
- Does not delete or reset the database
- Does not delete Docker volumes
- Does not touch `.env` or `.htpasswd`
- Does not restore seed data or ask backup/restore questions

If there are local uncommitted changes, `update.sh` will stop before pulling or rebuilding and show `git status --short`. Commit or stash the changes, then re-run.

Use `./setup.sh` for initial installation or when you need to re-initialize `.env`, change the port, or re-run the full first-time setup flow.

---

## What Event Map Does

Event Map is a browser-based geospatial tool for discovering regional farms, farmers markets, fairs, and festivals. Visitors browse a satellite map, click map pins for location details, and filter results by category, season, and crop type.

It includes a password-protected admin panel for managing locations, crops, and site content — with no coding required after setup.

---

## Key Features

- **Satellite/hybrid map** — Leaflet.js with Esri World Imagery tiles (no API key)
- **Category filtering** — farms, farmers markets, festivals, fairs
- **Month and crop filtering** — see what is in season right now
- **Pick-your-own (PYO) toggle** — filter to PYO-only locations
- **Organic / growing practices filter**
- **Location detail panel** — address, hours, phone, website, crops, amenities
- **Geolocation** — browser blue-dot (requires HTTPS; works via Cloudflare)
- **Admin panel** — add/edit/delete locations and crops via web UI
- **Credential management** — change admin username and password from the UI

---

## Architecture

```
Browser  →  Flask (port 8080, internal)  →  MySQL 8.0
              ├── REST API (/locations, /categories, ...)
              └── Static files (index.html, admin/, css/, js/)
```

Docker Compose manages two containers:

| Container | Role |
|-----------|------|
| `event-map-app` | Flask API + static file server |
| `event-map-db`  | MySQL 8.0 database |

A named Docker volume (`event_map_db_data`) provides persistent storage.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML/CSS/JS, Leaflet.js, Esri World Imagery |
| Backend | Flask (Python 3.12) |
| Database | MySQL 8.0 |
| Auth | bcrypt-hashed credentials via `.htpasswd` |
| Infrastructure | Docker Compose |
| DNS / SSL | Cloudflare proxied (optional) |

---

## Data Sources

The seed dataset (`api/data/seed.sql`) is an **opinionated starter dataset** curated for Mollie — a specific person in the Pittsburgh area. It reflects her preferences, her neighborhoods, and the farms, markets, butchers, trails, and events she actually cares about. It is not a neutral, universal dataset.

If you are running this app for yourself, you should expect to replace or supplement the seed data with locations relevant to your own area and interests. The seed is a starting point, not a canonical directory.

The dataset includes 300+ geocoded locations across the Pittsburgh region, with a focus on:
- Farms and CSAs in western Pennsylvania
- Farmers markets in Allegheny County and surrounding areas
- Festivals and fairs with seasonal scheduling
- Butcher shops and specialty meat markets
- Hiking trails and nature reserves in the Pittsburgh region

Locations are geocoded using coordinates from public directories, the US Census Geocoder API, and OpenStreetMap Nominatim.

---

## Runtime State and Persistence

| Item | Location |
|------|----------|
| Database | Docker volume `event_map_db_data` |
| Admin credentials | `.htpasswd` (host filesystem, bind-mounted into app container) |
| Secrets | `.env` (auto-generated, not committed) |

`.env` and `.htpasswd` are gitignored. Re-running `setup.sh` preserves existing passwords if `.env` already exists.

---

## Database Backup and Restore

### Regular local backup

```bash
./scripts/backup-db.sh
```

Saves a full compressed backup in two forms:

| File | Purpose |
|------|---------|
| `~/.event-map/backups/event-map-YYYYmmdd-HHMMSS.sql.gz` | Timestamped copy, kept indefinitely |
| `~/.event-map/backups/event-map-latest.sql.gz` | Always points to the most recent backup |

Run this before making any significant data changes. Backups live outside the repo and are never committed.

### Refreshing the public repo baseline seed

> **`api/data/seed.sql` is committed to a public GitHub repository.**
> Only refresh it when you intentionally want future fresh installs to start with the current curated data.
> Always inspect `git diff api/data/seed.sql` before committing — do not commit if you see private data.

There are two ways to create a seed snapshot:

#### Option A: Admin panel (recommended for Mollie/Charlie)

1. Log in to the Admin panel
2. Click the **Maintenance** tab
3. Click **Create Seed Snapshot**

This updates `api/data/seed.sql` in the local repo immediately. A timestamped backup is created automatically at `api/data/backups/seed-TIMESTAMP.sql` (not committed — covered by `.gitignore`).

The admin snapshot updates the **local repo file only**. To publish it to GitHub, run:

```bash
./publish-seed.sh
```

`publish-seed.sh` is a beginner-friendly script that:
- Shows the git diff so you can review what changed
- Asks for a commit message (default: `Update Mollie seed data`)
- Commits only seed-related files unless you choose otherwise
- Asks before pushing — never force-pushes
- Fails cleanly if the remote is not configured or authenticated

#### Option B: Terminal (full-featured)

```bash
./update-seed.sh
```

`update-seed.sh` guides you through the full backup-and-verify workflow:

1. Verifies Docker and MySQL are running
2. Creates a full timestamped safety backup (before changing anything)
3. Generates a **selective** seed — curated data only, runtime cache excluded
4. Runs a keyword safety scan on the generated seed
5. Shows exactly what will be written and prompts for confirmation
6. Writes `api/data/seed.sql` and prints the review commands

**What the seed includes:**
- `categories`, `locations`, `crops`, `notes`, `user_notes` — all curated place data
- `event_sources` — source keys, display names, enabled/disabled settings, coverage days

**What the seed excludes:**
- `external_events` data — runtime fetch cache; repopulated automatically on each refresh
- `event_sources` runtime timestamps — `last_success_at`, `last_attempt_at`, `last_error` reset to NULL
- Admin credentials — managed by `.htpasswd` on the host filesystem, not stored in the database

Do not commit `api/data/seed.sql` if `git diff` shows unexpected private data.

### How setup.sh chooses what to restore

When setting up a fresh database `setup.sh` checks for:

| Condition | Behavior |
|-----------|----------|
| Both repo baseline (`api/data/seed.sql`) and local backup (`~/.event-map/backups/event-map-latest.sql.gz`) exist | Asks which to use (1 = repo baseline, 2 = local backup, 3 = fresh) |
| Only local backup exists | Offers to restore from it |
| Only repo baseline exists | Loads the repo baseline automatically |
| Neither exists | Starts with an empty database |
| Database already has data | Skips restore entirely |

### Manual restore from local backup

```bash
zcat ~/.event-map/backups/event-map-latest.sql.gz | \
  docker exec -i event-map-db sh -lc \
  'mysql -h127.0.0.1 -P3306 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

---

## Month Filtering Behavior

Month filtering uses structured `season_start_month` / `season_end_month` fields stored on each location and each crop row.

**Rules:**
- When a month filter is active, only locations whose structured month range **overlaps** the selected month are shown.
- If an item has **no** structured month data (both fields are `NULL`), it is treated as **schedule unknown** and is **excluded** from month-filtered results.
- Farms may match via their crop-level season months even if the location-level season fields are blank.
- When **no month filter is active**, all items matching the other active filters are shown — schedule-unknown items appear normally.

### Why free-text dates are not used for filtering

The original `event_date` field (e.g., "July 6-11") is free text and cannot be reliably parsed for month comparisons. It is preserved in the database for existing records but is no longer shown as an editable field in the admin form. Month filtering uses only the structured month fields. Event-specific details (exact date, "second weekend") should go in the **Description / Site Info** field.

---

## Admin Schedule / Month Fields

The **Season / Schedule** section appears in the admin form for:

| Category | Season / Schedule section | Notes |
|----------|--------------------------|-------|
| farm | No (uses crop-level season months) | Crops have their own start/end months |
| farmers-market | Yes | Controls month filter visibility |
| festival | Yes | Controls month filter visibility |
| fair | Yes | Controls month filter visibility |
| other | Yes | Controls month filter visibility |
| butcher | Yes | Year-round businesses should set Jan (start) → Dec (end) |

**Active Month Start** and **Active Month End** define the range of months this item appears in when a month filter is active. Leave both blank if the schedule is unknown — the item will still appear when no month filter is active.

For year-round businesses (butchers), set Jan (start) and Dec (end) so they appear in all month-filtered results.

For a single-month event, set both start and end to the same month.

---

## Crop Selection (Admin)

When adding or editing a farm's crops, the crop name field shows suggestions from all crop names already used in the database (via a `<datalist>`). You can select an existing name or type a new one.

Crop names are normalized on save:
- Leading/trailing whitespace is removed
- Consecutive spaces are collapsed
- Names are lowercased to match the existing database convention

This prevents obvious duplicates like "Apple" vs "apple" or "blueberries " (trailing space).

---

## Address and Coordinate Behavior

| Case | Behavior |
|------|----------|
| Lat/lng provided | Those coordinates are used. Takes priority over address geocoding. |
| Lat/lng missing, address present | Backend attempts geocoding via Nominatim (OpenStreetMap). If successful, coordinates are stored. If geocoding fails or the service is unavailable, the record is saved without coordinates (no crash). |
| Lat/lng provided, no address | Saved normally. The item is mappable. |
| Neither coordinates nor address | Saved without coordinates. The item will not appear on the map but will appear in list view. |

Map markers are placed using stored coordinates. Raw address text is never used directly for map positioning.

---

## Duplicate Detection

Run the duplicate report script to identify likely duplicate records:

```bash
python3 scripts/find-duplicates.py
```

**This script is read-only.** It does not modify or delete any data.

The report identifies groups of records that match on:
- Category + normalized name + city
- Category + normalized name + county (catches city spelling variants)
- Category + address + city (catches renamed locations)

To investigate a flagged record, open:
```
http://localhost:<PORT>/admin/edit.html?id=<ID>
```

Do not run DELETE queries without verifying each record individually.

---

## API Endpoints

All public endpoints require no authentication.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/locations` | All locations (supports filters) |
| GET | `/locations/<id>` | Single location with crops |
| GET | `/categories` | All categories |
| GET | `/counties` | All counties |
| GET | `/crops/distinct` | Distinct crop names with counts |
| GET | `/locations/<id>/notes` | Notes for a location |
| POST | `/login` | Admin login |
| POST | `/logout` | Admin logout |

All endpoints also respond under the `/api/` prefix (e.g. `/api/locations`).

### Filter parameters for `/locations`

| Param | Example | Description |
|-------|---------|-------------|
| `category` | `?category=farm` | Filter by category |
| `month` | `?month=7` | Locations with in-season crops in that month |
| `crop` | `?crop=blueberries` | Filter by crop name |
| `pyo_only` | `?pyo_only=true` | Only pick-your-own crops |
| `organic` | `?organic=true` | Only organic locations |

---

## Admin Panel

- **Login:** `/admin/login.html`
- **Location list / Map admin:** `/admin/` (Map tab)
- **Edit / add location:** `/admin/edit.html?id=N`
- **Events admin:** `/admin/#events` (Events tab)

The admin panel has two tabs:

| Tab | Purpose |
|-----|---------|
| Map | Existing location/farm/market management |
| Events | Imported event feed — status by source, hide/unhide events, refresh cache |

**Default local admin login:**
```
username: meeks
password: meeks
```

> **Change these immediately after first login.** Use the Change Username / Change Password buttons in the admin panel header. Do not expose the admin interface publicly without setting a strong password.

Credentials are stored as a bcrypt hash in `.htpasswd` on the host filesystem. Sessions last 24 hours.

Event source attribution chips on the public Events page link to each source's homepage.

---

## Testing

```bash
# Health check
curl http://localhost:8090/health

# Location count
curl http://localhost:8090/locations | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'locations')"

# Container status
docker compose ps

# Logs
docker compose logs event-map-app
docker compose logs event-map-db
```

---

## Deployment Notes

- **Port:** setup.sh finds the next available port starting at 8090. The assigned port is written to `.env`.
- **HTTPS:** point a domain at the server IP and enable the Cloudflare proxy for automatic SSL. Geolocation (browser blue dot) requires HTTPS.
- **Existing volumes:** if a `event_map_db_data` volume already exists (prior install), the database is reused and the seed step is skipped if the `locations` table is already populated.
- **Re-running setup:** safe to re-run — passwords and credentials are preserved if `.env` and `.htpasswd` already exist.
- **Low-memory servers:** this app is designed to run on small private servers (~1 GiB RAM). `mysql/conf.d/low-memory.cnf` is mounted into the MySQL container and tunes InnoDB and connection limits for minimal footprint. A 2 GiB swapfile is recommended on machines with less than 2 GiB RAM.

---

## Small VPS / Oracle Always Free Notes

This deployment is designed for the Oracle Always Free tier (2 vCPU, ~1 GiB RAM) and similar small, private VPS hosts. It is not intended for high traffic.

### Swap

**Swap is strongly recommended on ~1 GiB RAM hosts.** Without it, MySQL and the Docker build process can trigger the Linux OOM killer.

Set up a 2 GiB swapfile on Ubuntu if one is not already present:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Verify:
```bash
free -h
```

### MySQL memory configuration

`mysql/conf.d/low-memory.cnf` is automatically mounted into the MySQL container. It sets conservative InnoDB and connection limits appropriate for a 1 GiB host:

- `innodb_buffer_pool_size = 128M`
- `performance_schema = OFF`
- `max_connections = 20`
- Per-session sort/read buffers reduced

Do not increase these values on the Oracle Always Free tier.

### First startup is slow

On a 1 GiB VPS, MySQL takes longer than on a developer laptop:

- First boot (volume initialization): **2–5 minutes is normal**
- Subsequent boots: **30–60 seconds**

`setup.sh` waits up to 300 seconds and prints progress every 15 seconds. If it times out, wait a moment and re-run.

### Event source refreshes may be slow

External source refreshes (CitySpark, Algolia) run in the background after startup and can take 30–60 seconds on a constrained host. This is expected behavior. The app remains available during refresh.

### Container log rotation

Both containers are configured with Docker's `json-file` log driver capped at **10 MB × 3 files** per container. On a tiny disk this keeps logs from growing unbounded without manual pruning.

### Check memory and container health

```bash
# Memory and swap usage
free -h

# Live container resource usage (one snapshot)
docker stats --no-stream

# Container status
docker ps
```

---

## Known Limitations

- Admin panel auth is session-based with bcrypt-verified credentials — no rate limiting on login attempts.
- Map default center is set to western Pennsylvania (40.5061, -79.8389, zoom 9). Adjust in `js/main_v2.js` for other regions.
- Geolocation requires HTTPS. On plain HTTP it silently does nothing.

---

## Roadmap / Future Work

- Location search by address or name
- User-submitted event suggestions with moderation queue
- Public event submission form
- Export to iCal / Google Calendar for events and fairs
- Mobile-optimized detail panel
