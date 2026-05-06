FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better caching
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API code
COPY api/ .

# Copy frontend files to static/ directory for Flask to serve
COPY index.html ./static/
COPY css ./static/css
COPY js ./static/js
COPY admin ./static/admin
COPY robots.txt ./static/

EXPOSE 8080

CMD ["python", "app.py"]
