# Mollie's Guide

A pick-your-own farm and farmers market map covering Pennsylvania, Ohio, and West Virginia. Shows 180+ locations on a hybrid aerial map with filtering by crop, month, category, and growing practices.

**Live site:** https://IP:Port  
**Admin panel:** https://IP:Port/admin/

---

## Deploy

### Part 1 — Install Docker (skip if already installed)

```bash
sudo apt update && sudo apt upgrade -y && sudo apt install -y git curl apache2-utils
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER
```

**Log out and back in** after this so the docker group takes effect, then verify:

```bash
docker --version && docker compose version
```

---

### Part 2 — Clone and run

```bash
git clone https://github.com/ApiFlier/event-map.git ./mollie && cd ./mollie && chmod +x setup.sh && ./setup.sh
```

That's it. The setup script:
1.  Automatically finds an available host port (starting at 8090).
2.  Generates a `.env` with random passwords and the selected port.
3.  Creates the admin login.
4.  Starts Docker containers.
5.  Restores the database automatically.

The final URL will be printed at the end of the script.

---

### After setup

- **Default admin login:** meeks / meeks — change it at `/admin/` immediately
- **Passwords:** stored in `/mollie/.env` — check there if you need them
- **Point your domain:** add an A record to your server IP, enable Cloudflare proxy for auto SSL

---

## Taking a Backup

Run this before making major changes:

```bash
docker exec mollies-db mysqldump -uroot \
  -p$(grep MYSQL_ROOT_PASSWORD /mollie/.env | cut -d= -f2) \
  mollies_guide > /mollie/api/data/mollies_backup.sql
```

Commit it to keep the repo backup current:

```bash
cd /mollie && git add api/data/mollies_backup.sql && git commit -m "db backup $(date +%Y-%m-%d)" && git push
```

---

## Tech Stack

- **Frontend:** Leaflet.js + Esri World Imagery tiles (no API key required)
- **Backend/Server:** Flask (Python) serving both REST API and static files
- **Database:** MySQL 8.0
- **Infrastructure:** Docker Compose
- **DNS/SSL:** Cloudflare (proxied)

---

## Project Structure

```
/mollie/
├── docker-compose.yml        # Container orchestration
├── setup.sh                  # Fresh deployment script
├── robots.txt
├── index.html                # Public map app
├── css/styles.css
├── js/
│   ├── api.js                # API abstraction layer
│   ├── map.js                # Leaflet map logic
│   ├── filters.js            # Filter UI
│   └── main.js               # App entry point
├── admin/
│   ├── admin.css
│   ├── admin.js              # Admin UI + auth logic
│   ├── login.html            # Admin login page
│   ├── index.html            # Farm list/search
│   └── edit.html             # Add/edit farm form
└── api/
    ├── Dockerfile
    ├── requirements.txt
    ├── app.py                # Flask API + Static server
    └── data/
        ├── schema.sql        # DB schema
        ├── mollies_backup.sql # Full DB backup
        └── scripts/          # Data import/maintenance scripts
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
| GET | `/crops/distinct` | Distinct crop names |
| GET | `/locations/<id>/notes` | Notes for a location |
| POST | `/login` | Admin login |
| POST | `/logout` | Admin logout |

*Note: All endpoints also support the `/api/` prefix for backward compatibility (e.g. `/api/locations`).*

### Filter parameters for `/locations`

| Param | Example | Description |
|-------|---------|-------------|
| `category` | `?category=farm` | Filter by category |
| `month` | `?month=7` | Locations with in-season crops in that month |
| `crop` | `?crop=blueberries` | Filter by crop name |
| `pyo_only` | `?pyo_only=true` | Only pick-your-own crops |
| `organic` | `?organic=true` | Only organic locations |

---

## Ports

| Port | Service |
|------|---------|
| 8090 | App (Frontend + API) |
| 3308 | MySQL (host-side, for local access if enabled) |

---

## Admin Panel

- **Login:** `/admin/login.html`
- **Location list:** `/admin/`
- **Edit/add location:** `/admin/edit.html?id=N`

Sessions last 30 days.

---

## Notes

- Map default center: Verona, PA (40.5061, -79.8389), zoom 9
- Geolocation (blue dot) requires HTTPS — works automatically via Cloudflare
