FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better caching
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API code
COPY api/ .

# Copy frontend files to static/ directory for Flask to serve
COPY index.html ./static/
COPY map.html ./static/
COPY css ./static/css
COPY js ./static/js
COPY admin ./static/admin
COPY robots.txt ./static/

EXPOSE 8080

# 1 worker: matches MySQL max_connections=20 (pool_size=15 per worker).
# --timeout 120: allows slow startup on the Oracle Always Free VPS.
CMD ["gunicorn", "--workers", "1", "--timeout", "120", "--bind", "0.0.0.0:8080", "app:app"]
