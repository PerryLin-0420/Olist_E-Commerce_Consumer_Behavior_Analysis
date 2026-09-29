-- Derived tables built on top of the raw layer.

-- One row per zip code prefix so customers/sellers can join geolocation 1:1.
-- Exact duplicate rows are removed and points outside Brazil's bounding box
-- are excluded before averaging coordinates.
CREATE OR REPLACE TABLE geolocation_zip AS
WITH dedup AS (
    SELECT DISTINCT *
    FROM geolocation
    WHERE geolocation_lat BETWEEN -34.0 AND 5.5
      AND geolocation_lng BETWEEN -74.0 AND -34.0
)
SELECT
    geolocation_zip_code_prefix,
    avg(geolocation_lat)    AS geolocation_lat,
    avg(geolocation_lng)    AS geolocation_lng,
    mode(geolocation_city)  AS geolocation_city,
    mode(geolocation_state) AS geolocation_state,
    count(*)                AS point_count
FROM dedup
GROUP BY geolocation_zip_code_prefix
ORDER BY geolocation_zip_code_prefix;
