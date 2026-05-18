-- ============================================================
-- Event Map — Mollie activity farms, fossil places, and
--             Pittsburgh cultural/membership destinations
--
-- IDEMPOTENT: safe to run against both a fresh database (no
-- prior changes) and a database where some changes already
-- exist.  Every INSERT uses WHERE NOT EXISTS; every crop
-- insert checks for an existing row first.  UPDATEs are
-- always safe to re-apply.
--
-- Usage (from repo root):
--   DB_PASS=$(grep DB_PASS .env | cut -d= -f2)
--   docker compose exec -T db \
--     mysql -u event_map -p"$DB_PASS" event_map \
--     < scripts/content/add-mollie-activity-farms-and-fossils.sql
--
-- What this script does:
--   1. Refreshes notes on 5 existing Western PA farms — removes
--      any kid-focused framing; emphasises adult experiences,
--      animal encounters, seasonal attractions, and agritourism.
--   2. Adds activity crops (is_pyo=0) to existing farms for
--      crop-filter discoverability.
--   3. Removes the 'kids activities' crop tag from Trax Farms.
--   4. Inserts 3 new destination farms if not already present:
--        Hozak Farms, Janoski's Farm and Greenhouse,
--        Brown Hill Farms (NEPA reference farm).
--   5. Inserts 2 fossil/geology places under Other if absent:
--        Carnegie Museum of Natural History,
--        Penn Dixie Fossil Park.
--   6. Inserts 4 Pittsburgh cultural/membership destinations
--      under Other if absent:
--        Pittsburgh Zoo & PPG Aquarium,
--        National Aviary,
--        Phipps Conservatory and Botanical Gardens,
--        Carnegie Science Center.
--   7. Sets geocoordinates for all new entries where known.
--   8. Adds crops for new locations.
--
-- DOES NOT:
--   Touch unrelated locations, events, or external_events.
--   Delete any data except the specific 'kids activities' crop
--   on Trax Farms.
--   Reference columns (seed_managed, user_modified, hidden)
--   that no longer exist in the live DB.
-- ============================================================

-- ============================================================
-- SECTION 1 — Update notes on existing Western PA farms
--   (adult-focused framing; animal encounters not kid-framing)
-- ============================================================

UPDATE locations SET notes =
  'Destination activity farm and agritourism stop. PYO berries, apples, and pumpkins. '
  'Petting zoo with animal encounters, seasonal corn maze, hayrides, concessions, '
  'and gift shop. Fall festival season September–October. '
  'Verify current seasonal offerings before visiting.'
WHERE name = 'Triple B Farms' AND city = 'Monongahela' AND state = 'PA';

UPDATE locations SET notes =
  'Large destination activity farm and market in Finleyville. '
  'Seasonal corn maze, hayrides, animal encounters at the petting zoo, '
  'pumpkin patch, and fall festival. '
  'PYO strawberries and blueberries in season. Farm market open seasonally. '
  'Verify current offerings before visiting.'
WHERE name = 'Trax Farms' AND city = 'Finleyville' AND state = 'PA';

UPDATE locations SET notes =
  'Destination activity farm with PYO strawberries, peaches, apples, and pumpkins. '
  'Sunflower fields in summer, pumpkin patch in fall, and seasonal farm activities. '
  'Farm market and fresh flowers. Agritourism destination. '
  'Verify current seasonal offerings before visiting.'
WHERE name = 'Simmons Farm' AND city = 'McMurray' AND state = 'PA';

UPDATE locations SET notes =
  'Farm market and activity farm destination with PYO apples, blueberries, flowers, and pumpkins. '
  'Seasonal farm stand and fall activities. Verify current seasonal offerings before visiting.'
WHERE name = 'Shenot Farm and Market' AND city = 'Wexford' AND state = 'PA';

UPDATE locations SET notes =
  'Well-known farm market, orchard, and agritourism destination in Wexford. '
  'PYO fruit, fresh-pressed apple cider, bakery, and seasonal fall events. '
  'A classic Western PA activity farm stop. '
  'Verify current seasonal offerings before visiting.'
WHERE name = 'Soergel Orchards' AND city = 'Wexford' AND state = 'PA';

UPDATE locations SET notes =
  'Sunflower and activity farm in western Allegheny County. '
  'U-pick sunflowers, pumpkin patch, and seasonal fall festival events. '
  'Verify address, hours, and seasonal availability before visiting.'
WHERE name = 'Hozak Farms' AND city = 'Clinton' AND state = 'PA';

UPDATE locations SET notes =
  'Destination agritourism and activity farm in northeastern PA. '
  'Tulip fields in spring, sunflower fields in summer, pumpkin patch, corn maze, '
  'fall festival, animal encounters, and photo ops. '
  'Verify hours and seasonal offerings before visiting. '
  'Out-of-area day trip — plan accordingly.'
WHERE name = 'Brown Hill Farms' AND city = 'Tunkhannock' AND state = 'PA';

-- ============================================================
-- SECTION 2 — Activity crops for existing farms
--   (is_pyo=0: non-harvest activity tag for discoverability)
--   Each INSERT is guarded: only inserts if the crop is absent.
-- ============================================================

-- ── Triple B Farms ─────────────────────────────────────────
SET @loc = (SELECT id FROM locations
            WHERE name = 'Triple B Farms' AND city = 'Monongahela' AND state = 'PA' LIMIT 1);

INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'corn maze',         0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'corn maze');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'hayrides',          0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'hayrides');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival',     0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'petting zoo',       0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'petting zoo');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'animal encounters', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'animal encounters');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm',     0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',       0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Trax Farms ─────────────────────────────────────────────
SET @loc = (SELECT id FROM locations
            WHERE name = 'Trax Farms' AND city = 'Finleyville' AND state = 'PA' LIMIT 1);

INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'corn maze',         0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'corn maze');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'hayrides',          0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'hayrides');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival',     0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'farm market',       0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'farm market');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'petting zoo',       0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'petting zoo');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'animal encounters', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'animal encounters');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm',     0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',       0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Simmons Farm ───────────────────────────────────────────
SET @loc = (SELECT id FROM locations
            WHERE name = 'Simmons Farm' AND city = 'McMurray' AND state = 'PA' LIMIT 1);

INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'sunflowers',    0, 7,  9 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'sunflowers');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival', 0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'farm market',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'farm market');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Shenot Farm and Market ─────────────────────────────────
SET @loc = (SELECT id FROM locations
            WHERE name = 'Shenot Farm and Market' AND city = 'Wexford' AND state = 'PA' LIMIT 1);

INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'farm market',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'farm market');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival', 0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Soergel Orchards ───────────────────────────────────────
SET @loc = (SELECT id FROM locations
            WHERE name = 'Soergel Orchards' AND city = 'Wexford' AND state = 'PA' LIMIT 1);

INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'farm market',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'farm market');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'cider',         0, 9, 11 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'cider');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival', 0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ============================================================
-- SECTION 3 — Remove outdated / incorrectly framed crop tags
-- ============================================================

-- Remove 'kids activities' from Trax Farms (reframed as seasonal attractions;
-- 'petting zoo', 'animal encounters', 'corn maze', 'hayrides' cover the space)
DELETE FROM crops
WHERE location_id = (
    SELECT id FROM locations
    WHERE name = 'Trax Farms' AND city = 'Finleyville' AND state = 'PA' LIMIT 1
) AND name = 'kids activities';

-- ============================================================
-- SECTION 4 — New destination / activity farms (insert if absent)
-- ============================================================

-- ── Hozak Farms, Clinton PA ────────────────────────────────
INSERT INTO locations (name, city, state, category_id, county, notes,
                       season_start_month, season_end_month)
SELECT
  'Hozak Farms', 'Clinton', 'PA',
  (SELECT id FROM categories WHERE name = 'farm' LIMIT 1),
  'Allegheny',
  'Sunflower and activity farm in western Allegheny County. '
  'U-pick sunflowers, pumpkin patch, and seasonal fall festival events. '
  'Verify address, hours, and seasonal availability before visiting.',
  7, 10
WHERE NOT EXISTS (
  SELECT 1 FROM locations WHERE name = 'Hozak Farms' AND city = 'Clinton' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Hozak Farms' AND city = 'Clinton' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4890892, lng = -80.2949650
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'sunflowers',    1, 7,  9 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'sunflowers');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'pumpkins',      1, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'pumpkins');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival', 0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Janoski's Farm and Greenhouse, Clinton PA ──────────────
INSERT INTO locations (name, city, state, category_id, county, notes,
                       season_start_month, season_end_month)
SELECT
  "Janoski's Farm and Greenhouse", 'Clinton', 'PA',
  (SELECT id FROM categories WHERE name = 'farm' LIMIT 1),
  'Allegheny',
  'Farm and greenhouse in western Allegheny County with seasonal flowers, '
  'produce, and farm market. Verify address, hours, and current offerings before visiting.',
  4, 10
WHERE NOT EXISTS (
  SELECT 1 FROM locations WHERE name = "Janoski's Farm and Greenhouse" AND city = 'Clinton' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = "Janoski's Farm and Greenhouse" AND city = 'Clinton' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4890892, lng = -80.2949650
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'flowers',       1, 5,  9 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'flowers');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'farm market',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'farm market');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm', 0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',   0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ── Brown Hill Farms, Tunkhannock PA (NEPA reference farm) ─
INSERT INTO locations (name, city, state, category_id, county, notes,
                       season_start_month, season_end_month)
SELECT
  'Brown Hill Farms', 'Tunkhannock', 'PA',
  (SELECT id FROM categories WHERE name = 'farm' LIMIT 1),
  'Wyoming',
  'Destination agritourism and activity farm in northeastern PA. '
  'Tulip fields in spring, sunflower fields in summer, pumpkin patch, corn maze, '
  'fall festival, animal encounters, and photo ops. '
  'Verify hours and seasonal offerings before visiting. '
  'Out-of-area day trip — plan accordingly.',
  4, 10
WHERE NOT EXISTS (
  SELECT 1 FROM locations WHERE name = 'Brown Hill Farms' AND city = 'Tunkhannock' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Brown Hill Farms' AND city = 'Tunkhannock' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 41.5385159, lng = -75.9468440
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'tulips',           1, 4,  5 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'tulips');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'sunflowers',       1, 7,  9 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'sunflowers');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'pumpkins',         1, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'pumpkins');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'corn maze',        0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'corn maze');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'fall festival',    0, 9, 10 WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'fall festival');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'animal encounters',0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'animal encounters');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'activity farm',    0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'activity farm');
INSERT INTO crops (location_id, name, is_pyo, season_start_month, season_end_month)
SELECT @loc, 'agritourism',      0, NULL, NULL WHERE @loc IS NOT NULL AND NOT EXISTS (SELECT 1 FROM crops WHERE location_id = @loc AND name = 'agritourism');

-- ============================================================
-- SECTION 5 — Fossil / geology places (category: other)
-- ============================================================

-- ── Carnegie Museum of Natural History, Pittsburgh ─────────
INSERT INTO locations (name, address, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'Carnegie Museum of Natural History',
  '4400 Forbes Ave', 'Pittsburgh', 'PA', '15213',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Allegheny',
  'World-class natural history museum with one of the finest dinosaur fossil '
  'collections in North America. Dinosaur Hall features Diplodocus and Apatosaurus. '
  'Hillman Hall of Minerals and Gems. Part of the Carnegie Museums of Pittsburgh '
  'membership. Admission fee applies.',
  'https://carnegiemnh.org',
  'https://carnegiemnh.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE name = 'Carnegie Museum of Natural History' AND city = 'Pittsburgh' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Carnegie Museum of Natural History' AND city = 'Pittsburgh' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4437092, lng = -79.9490541
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ── Penn Dixie Fossil Park, Hamburg NY (out-of-area day trip)
INSERT INTO locations (name, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'Penn Dixie Fossil Park',
  'Hamburg', 'NY', '14075',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Erie County NY',
  'Public fossil park near Buffalo, NY where visitors search for and keep '
  'Devonian marine fossils including trilobites and brachiopods. '
  'Run by the Hamburg Natural History Society. '
  'About 3.5 hours from Pittsburgh — an out-of-area day trip for dedicated fossil enthusiasts. '
  'Admission fee applies. Verify hours, rules, and access before visiting.',
  'https://penndixie.org',
  'https://penndixie.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE name = 'Penn Dixie Fossil Park' AND city = 'Hamburg' AND state = 'NY'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Penn Dixie Fossil Park' AND city = 'Hamburg' AND state = 'NY' LIMIT 1);
UPDATE locations SET lat = 42.7162930, lng = -78.8287170
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ============================================================
-- SECTION 6 — Pittsburgh cultural / membership destinations
--             (category: other; adult-focused)
-- ============================================================

-- ── Pittsburgh Zoo & PPG Aquarium ─────────────────────────
INSERT INTO locations (name, address, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'Pittsburgh Zoo & PPG Aquarium',
  '7370 Baker St', 'Pittsburgh', 'PA', '15206',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Allegheny',
  'Full-service zoo and aquarium in Highland Park. '
  'Big cats, elephants, polar bears, giraffes, sea life, and more. '
  'Great for animal encounters and an outdoor day. Membership available.',
  'https://www.pittsburghzoo.org',
  'https://www.pittsburghzoo.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE (name LIKE '%Pittsburgh Zoo%' OR name LIKE '%PPG Aquarium%') AND city = 'Pittsburgh' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Pittsburgh Zoo & PPG Aquarium' AND city = 'Pittsburgh' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4835453, lng = -79.9191822
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ── National Aviary ────────────────────────────────────────
INSERT INTO locations (name, address, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'National Aviary',
  '700 Arch St', 'Pittsburgh', 'PA', '15212',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Allegheny',
  'Pittsburgh''s world-class bird sanctuary with 500+ species across immersive indoor aviaries. '
  'Free-flight encounters, tropical birds, penguins, and raptors. '
  'Relaxed and adult-friendly. Membership available.',
  'https://www.aviary.org',
  'https://www.aviary.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE name LIKE '%National Aviary%' AND city = 'Pittsburgh' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'National Aviary' AND city = 'Pittsburgh' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4534125, lng = -80.0099541
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ── Phipps Conservatory and Botanical Gardens ──────────────
INSERT INTO locations (name, address, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'Phipps Conservatory and Botanical Gardens',
  '1 Schenley Dr', 'Pittsburgh', 'PA', '15213',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Allegheny',
  'Victorian greenhouse and botanical gardens in Schenley Park. '
  'Rotating seasonal exhibits, tropical rooms, outdoor gardens, and regular floral shows. '
  'Great for photos, walks, and flowers in any season. '
  'Admission fee; membership available.',
  'https://phipps.conservatory.org',
  'https://phipps.conservatory.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE name LIKE '%Phipps%' AND city = 'Pittsburgh' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Phipps Conservatory and Botanical Gardens' AND city = 'Pittsburgh' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4423993, lng = -79.9532112
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ── Carnegie Science Center ────────────────────────────────
INSERT INTO locations (name, address, city, state, zip, category_id, county,
                       notes, website, source_url)
SELECT
  'Carnegie Science Center',
  '1 Allegheny Ave', 'Pittsburgh', 'PA', '15212',
  (SELECT id FROM categories WHERE name = 'other' LIMIT 1),
  'Allegheny',
  'Hands-on science and technology museum on Pittsburgh''s North Shore. '
  'Exhibits, USS Requin submarine tour, giant-screen cinema, and planetarium. '
  'Part of the Carnegie Museums of Pittsburgh membership. Admission fee applies.',
  'https://carnegiesciencecenter.org',
  'https://carnegiesciencecenter.org'
WHERE NOT EXISTS (
  SELECT 1 FROM locations
  WHERE name LIKE '%Carnegie Science%' AND city = 'Pittsburgh' AND state = 'PA'
);

SET @loc = (SELECT id FROM locations WHERE name = 'Carnegie Science Center' AND city = 'Pittsburgh' AND state = 'PA' LIMIT 1);
UPDATE locations SET lat = 40.4456300, lng = -80.0179310
  WHERE id = @loc AND (lat IS NULL OR lng IS NULL);

-- ============================================================
-- End of patch
-- ============================================================
