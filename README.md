# Mollie's Guide

A pick-your-own farm map for Pennsylvania, built for Mollie. Shows 90+ farms on a hybrid aerial map with filtering by crop, month, category, and growing practices.

**Live site:** https://meeks.cc  
**Admin panel:** https://meeks.cc/admin/

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
        ├── schema.sql        # DB schema
        ├── mollies_guide_geocoded.json  # Original 43 farms
        ├── mollie.json       # Additional farms (JSON format)
        ├── mollie_geocoded.json  # Additional farms with coords
        └── scripts/
            ├── geocode.py
            └── load_db.py
```

---

## Fresh Deployment

### Prerequisites

- Ubuntu 20.04+ server
- Docker + Docker Compose installed
- Domain pointed at server (or Cloudflare proxied)
- A database backup file (`.sql`) from a previous deployment

### Step 1 — Clone the repo

```bash
git clone https://github.com/ApiFlier/Mollie.git /mollie
cd /mollie
```

### Step 2 — Create `.env`

This file is **not in git** — you must create it manually.

```bash
cat > /mollie/.env << 'EOF'
MYSQL_ROOT_PASSWORD=your_root_password_here
DB_PASSWORD=your_db_password_here
FLASK_SECRET=your_long_random_secret_here
EOF
```

Generate a good FLASK_SECRET with:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 3 — Create `.htpasswd`

This file holds the admin login credentials and is **not in git**.

Install the tool if needed:
```bash
sudo apt install apache2-utils -y
```

Create the file:
```bash
htpasswd -B -c /mollie/.htpasswd yourusername
# Enter password when prompted
```

### Step 4 — Start containers

```bash
cd /mollie
docker compose up -d
```

Wait about 15 seconds for MySQL to initialize, then check everything is healthy:
```bash
docker compose ps
```

All three containers (`mollies-db`, `mollies-api`, `mollies-frontend`) should show as running/healthy.

### Step 5 — Restore the database

Copy your backup `.sql` file to the server, then:

```bash
docker exec -i mollies-db mysql \
  -uroot -p$(grep MYSQL_ROOT_PASSWORD /mollie/.env | cut -d= -f2) \
  mollies_guide < /path/to/your/backup.sql
```

Verify the restore:
```bash
docker exec mollies-db mysql \
  -umollies -p$(grep DB_PASSWORD /mollie/.env | cut -d= -f2) \
  mollies_guide -se "SELECT COUNT(*) FROM locations;"
```

Should return 92 (or however many farms are in your backup).

### Step 6 — Verify

- Public map: http://your-server-ip:8090
- Admin panel: http://your-server-ip:8090/admin/
- API health: http://your-server-ip:8091/health

If using Cloudflare, point your domain at the server and enable the proxy — SSL is handled automatically.

---

## Automated Setup

Instead of steps 2-5 manually, you can run the included setup script:

```bash
cd /mollie
chmod +x setup.sh
./setup.sh
```

The script will prompt you for all required values and handle the rest. You still need to provide a backup `.sql` file path.

---

## Admin Panel

The admin panel lives at `/admin/` and requires login.

- **Login:** `/admin/login.html`
- **Farm list:** `/admin/` (redirects to login if not authenticated)
- **Edit/add farm:** `/admin/edit.html?id=N`

Sessions last 30 days. To change your password, log in and use the "Change Password" button in the admin header.

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

### Filter parameters for `/api/locations`

- `?category=orchard`
- `?month=7` (farms with in-season crops in July)
- `?crop=Blueberries`
- `?pyo_only=true`
- `?organic=true`

Auth-required endpoints (POST/PUT/DELETE for locations, crops, notes, and credentials) require a valid session cookie from `/api/login`.

---

## Updating Farm Data

### Adding farms via admin panel
Log in at `/admin/`, click **+ Add Location**, fill out the form.

### Bulk import via JSON
See `api/data/mollie.json` for the expected format. Run the load script:
```bash
docker exec mollies-api python3 /app/data/scripts/load_db.py
```

---

## Taking a Backup

```bash
docker exec mollies-db mysqldump \
  -umollies -p$(grep DB_PASSWORD /mollie/.env | cut -d= -f2) \
  mollies_guide > ~/mollies_backup_$(date +%Y%m%d).sql
```

Store this file somewhere off the server (Google Drive, Dropbox, etc.). It's the only copy of the farm data.

---

## Ports

| Port | Service |
|------|---------|
| 8090 | nginx (public frontend) |
| 8091 | Flask API (internal, proxied through nginx) |
| 3308 | MySQL (host-side, for local access) |

---

## Notes

- Map default center: Verona, PA (40.5061, -79.8389), zoom 9
- Geolocation (blue dot) works over HTTPS — enabled via Cloudflare
- 7 farms have city-center coordinates due to rural addresses that couldn't be geocoded precisely: Blueberry Mountain Farm, Bohlayer's Orchards, Shirey's Blueberry Hill, JB Tree Farm, Dries Orchard, Wiseguys, Susquehanna Orchards
