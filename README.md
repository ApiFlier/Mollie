# Mollie's Guide

A pick-your-own farm map for Pennsylvania, built for Mollie. Shows 90+ farms on a hybrid aerial map with filtering by crop, month, category, and growing practices.

**Live site:** https://meeks.cc  
**Admin panel:** https://meeks.cc/admin/

---

## Quick Deploy (Fresh Ubuntu Server)

These steps assume a brand new headless Ubuntu 20.04+ server with nothing installed.

### 1 — System update and dependencies

```bash
sudo apt update && sudo apt upgrade -y && sudo apt install -y git curl apache2-utils
```

### 2 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER
```

**Log out and back in** after this so the docker group takes effect:
```bash
exit
# reconnect via SSH, then verify:
docker --version && docker compose version
```

### 3 — Clone and run setup

```bash
git clone https://github.com/ApiFlier/Mollie.git /mollie && cd /mollie && ./setup.sh
```

That's it. The setup script handles the `.env`, admin credentials, Docker containers, and database restore automatically.

### 4 — ⚠️ Change the default password immediately

The setup script creates a default login of **meeks / meeks**. The first thing you should do after the site loads is change it:

1. Go to `http://your-server-ip:8090/admin/`
2. Log in with **meeks / meeks**
3. Click **Change Password** in the admin header
4. Set a real password and don't forget it

**Do not leave the default credentials in place.**

### 5 — Point your domain (if using Cloudflare)

- Add an A record pointing your domain at the server's IP
- Enable the Cloudflare proxy (orange cloud)
- SSL is handled automatically — no cert setup needed

---

## Tech Stack

- **Frontend:** Leaflet.js + Esri World Imagery tiles (no API key required)
- **Backend:** Flask (Python) REST API
- **Database:** MySQL 8.0
- **Server:** nginx (reverse proxy + static files)
- **Infrastructure:** Docker Compose
- **DNS/SSL:** Cloudflare (proxied)

---

## Project Structure

```
/mollie/
├── docker-compose.yml        # Container orchestration
├── nginx.conf                # nginx config
├── proxy_pass.conf           # nginx proxy headers
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
    ├── app.py                # Flask API
    └── data/
        ├── schema.sql               # DB schema
        ├── mollies_backup.sql       # Full DB backup (all farms)
        ├── mollies_guide_geocoded.json
        ├── mollie.json
        ├── mollie_geocoded.json
        └── scripts/
            ├── geocode.py
            └── load_db.py
```

---

## API Endpoints

All public endpoints require no authentication.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/locations` | All locations (supports filters) |
| GET | `/api/locations/<id>` | Single location |
| GET | `/api/categories` | All categories |
| GET | `/api/counties` | All counties |
| GET | `/api/crops/distinct` | Distinct crop names |
| GET | `/api/locations/<id>/notes` | Notes for a location |
| POST | `/api/login` | Admin login |
| POST | `/api/logout` | Admin logout |

Auth-required endpoints (POST/PUT/DELETE for locations, crops, notes, and credentials) require a valid session cookie from `/api/login`.

### Filter parameters for `/api/locations`

| Param | Example | Description |
|-------|---------|-------------|
| `category` | `?category=orchard` | Filter by category |
| `month` | `?month=7` | Farms with in-season crops in that month |
| `crop` | `?crop=Blueberries` | Filter by crop name |
| `pyo_only` | `?pyo_only=true` | Only pick-your-own crops |
| `organic` | `?organic=true` | Only organic farms |

---

## Ports

| Port | Service |
|------|---------|
| 8090 | nginx (public frontend) |
| 8091 | Flask API (internal, proxied through nginx) |
| 3308 | MySQL (host-side, for local access) |

---

## Admin Panel

- **Login:** `/admin/login.html`
- **Farm list:** `/admin/` (redirects to login if not authenticated)
- **Edit/add farm:** `/admin/edit.html?id=N`

Sessions last 30 days.

---

## Taking a Backup

Always run this before making major changes:

```bash
docker exec mollies-db mysqldump -umollies -p$(grep DB_PASSWORD /mollie/.env | cut -d= -f2) mollies_guide > ~/mollies_backup_$(date +%Y%m%d).sql
```

---

## Updating Farm Data

**Via admin panel:** Log in at `/admin/`, click **+ Add Location**.

**Via bulk JSON import:** See `api/data/mollie.json` for the expected format, then run the load script:
```bash
docker exec mollies-api python3 /app/data/scripts/load_db.py
```

---

## Notes

- Map default center: Verona, PA (40.5061, -79.8389), zoom 9
- Geolocation (blue dot) requires HTTPS — works automatically via Cloudflare
- 7 farms use city-center coordinates due to rural addresses that couldn't be geocoded: Blueberry Mountain Farm, Bohlayer's Orchards, Shirey's Blueberry Hill, JB Tree Farm, Dries Orchard, Wiseguys, Susquehanna Orchards
