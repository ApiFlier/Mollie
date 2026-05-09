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
    payment_methods JSON,
    amenities JSON,
    organic BOOLEAN DEFAULT FALSE,
    pesticide_free BOOLEAN DEFAULT FALSE,
    low_chemical BOOLEAN DEFAULT FALSE,
    notes TEXT,
    source_url VARCHAR(512),
    last_verified DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    INDEX idx_category (category_id),
    INDEX idx_county (county),
    INDEX idx_geo (lat, lng)
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
    ('farm', 'apple', '#8b2331', 10),
    ('farmers-market', 'basket', '#7a8b5a', 20),
    ('festival', 'party', '#5d3a6b', 30),
    ('fair', 'ferris-wheel', '#5d3a6b', 40),
    ('other', 'pin', '#c4633a', 50);

CREATE TABLE IF NOT EXISTS notes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    location_id INT NOT NULL,
    note TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE,
    INDEX idx_location (location_id),
    INDEX idx_created (created_at)
);
