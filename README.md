# Event Map

A self-hosted event discovery map for regional farms, farmers markets, festivals, and local destinations. Displays 180+ locations on a hybrid aerial/satellite map with filtering by category, month, crop, and growing practices.

---

## Quick Start

```bash
git clone https://github.com/ApiFlier/event-map.git event-map
cd event-map
chmod +x setup.sh
./setup.sh
```

`setup.sh` will:
- Generate `.env` automatically with random passwords and secrets
- Create an admin login with a randomly generated password (shown once during setup)
- Find an available host port automatically (starting at 8090)
- Build and start the Docker containers
- Create or reuse a persistent Docker-managed database volume (`event_map_db_data`)
- Load the seed dataset (180+ geocoded locations)
- Print the local URL when done

No external API keys required.

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

The seed dataset (`api/data/seed.sql`) contains 180+ geocoded locations covering Pennsylvania, Ohio, and West Virginia sourced from public directories and geocoded via the US Census Geocoder API.

Source JSON files used to build the dataset are in `api/data/`:
- `mollie_farms.json` — pick-your-own farms and farm stands
- `mollie_markets.json` — farmers markets
- `mollie_festivals.json` — county fairs and festivals

Import and geocoding scripts are in `api/scripts/`.

---

## Runtime State and Persistence

| Item | Location |
|------|----------|
| Database | Docker volume `event_map_db_data` |
| Admin credentials | `.htpasswd` (host filesystem, bind-mounted into app container) |
| Secrets | `.env` (auto-generated, not committed) |

`.env` and `.htpasswd` are gitignored. Re-running `setup.sh` preserves existing passwords if `.env` already exists.

To take a manual backup at any time:

```bash
docker exec event-map-db mysqldump -uroot \
  -p$(grep MYSQL_ROOT_PASSWORD .env | cut -d= -f2) \
  event_map > api/data/seed.sql
```

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
- **Location list:** `/admin/`
- **Edit / add location:** `/admin/edit.html?id=N`

**Default local admin login:**
```
username: meeks
password: meeks
```

> **Change these immediately after first login.** Use the Change Username / Change Password buttons in the admin panel header. Do not expose the admin interface publicly without setting a strong password.

Credentials are stored as a bcrypt hash in `.htpasswd` on the host filesystem. Sessions last 24 hours.

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
