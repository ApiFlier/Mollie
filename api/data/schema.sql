-- Event Map schema
-- Charset/collation handled by MySQL container env vars

CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    icon VARCHAR(32),
    color VARCHAR(16),
    display_order INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS locations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category_id INT,
    county VARCHAR(64),
    address VARCHAR(255),
    city VARCHAR(128),
    state CHAR(2),
    zip VARCHAR(10),
    lat DECIMAL(10, 7),
    lng DECIMAL(10, 7),
    phone VARCHAR(32),
    alt_phone VARCHAR(32),
    fax VARCHAR(32),
    email VARCHAR(255),
    website VARCHAR(512),
    facebook_url VARCHAR(512),
    hours VARCHAR(512),
    -- event_date is legacy free-text; preserved for existing data but not shown in admin form.
    -- Use season_start_month / season_end_month for structured month filtering.
    event_date VARCHAR(255),
    season_start_month TINYINT,
    season_end_month TINYINT,
    payment_methods JSON,
    amenities JSON,
    organic BOOLEAN DEFAULT FALSE,
    pesticide_free BOOLEAN DEFAULT FALSE,
    low_chemical BOOLEAN DEFAULT FALSE,
    notes TEXT,
    source_url VARCHAR(512),
    last_verified DATE,
    seed_managed BOOLEAN DEFAULT FALSE,
    user_modified BOOLEAN DEFAULT FALSE,
    hidden BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    INDEX idx_category (category_id),
    INDEX idx_county (county),
    INDEX idx_geo (lat, lng),
    INDEX idx_season (season_start_month, season_end_month)
);

CREATE TABLE IF NOT EXISTS crops (
    id INT AUTO_INCREMENT PRIMARY KEY,
    location_id INT NOT NULL,
    name VARCHAR(128) NOT NULL,
    is_pyo BOOLEAN DEFAULT TRUE,
    season_start_month TINYINT,
    season_end_month TINYINT,
    notes TEXT,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE,
    INDEX idx_location (location_id),
    INDEX idx_season (season_start_month, season_end_month),
    INDEX idx_name (name)
);

-- Seed categories
INSERT INTO categories (name, icon, color, display_order) VALUES
    ('farm', 'apple', '#2e6b3e', 10),
    ('farmers-market', 'basket', '#7a8b5a', 20),
    ('festival', 'party', '#5d3a6b', 30),
    ('fair', 'ferris-wheel', '#5d3a6b', 40),
    ('other', 'pin', '#c4633a', 50),
    ('butcher', 'shop', '#7f1d1d', 55),
    ('hiking-trails', 'trail', '#5e9e6e', 57);

CREATE TABLE IF NOT EXISTS notes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    location_id INT NOT NULL,
    note TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE,
    INDEX idx_location (location_id),
    INDEX idx_created (created_at)
);

CREATE TABLE IF NOT EXISTS event_sources (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_key       VARCHAR(64) NOT NULL UNIQUE,
    display_name     VARCHAR(128) NOT NULL,
    enabled          BOOLEAN DEFAULT TRUE,
    last_success_at  DATETIME,
    last_attempt_at  DATETIME,
    last_error       TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_events (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    source_key              VARCHAR(64) NOT NULL,
    source_event_id         VARCHAR(255),
    source_url              VARCHAR(1024),
    official_url            VARCHAR(1024),
    title                   VARCHAR(512) NOT NULL,
    description_short       TEXT,
    start_datetime          DATETIME,
    end_datetime            DATETIME,
    date_label              VARCHAR(128),
    venue_name              VARCHAR(255),
    address                 VARCHAR(255),
    city                    VARCHAR(128),
    state                   CHAR(2),
    postal_code             VARCHAR(10),
    latitude                DECIMAL(10,7),
    longitude               DECIMAL(10,7),
    category                VARCHAR(64),
    image_url               VARCHAR(1024),
    admission               VARCHAR(255),
    distance_miles          DECIMAL(6,2),
    estimated_drive_minutes INT,
    direction_bucket        VARCHAR(16),
    normalized_fingerprint  VARCHAR(64),
    raw_source_json         MEDIUMTEXT,
    hidden                  BOOLEAN DEFAULT FALSE,
    saved                   BOOLEAN DEFAULT FALSE,
    first_seen_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_source        (source_key),
    INDEX idx_fingerprint   (normalized_fingerprint),
    INDEX idx_start         (start_datetime),
    INDEX idx_hidden        (hidden),
    INDEX idx_saved         (saved)
);
