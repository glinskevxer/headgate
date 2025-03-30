-- Supplemental wells, what they pumped, and the plans that cover them.

CREATE TABLE well (
    well_id             TEXT PRIMARY KEY,
    decree              TEXT NOT NULL REFERENCES water_right(decree),
    distance_feet       TEXT NOT NULL,
    storativity         TEXT NOT NULL,
    transmissivity      TEXT NOT NULL,
    capacity_gpm        TEXT NOT NULL,
    annual_limit_af     TEXT
);

CREATE TABLE well_pumping (
    well_id             TEXT NOT NULL REFERENCES well(well_id),
    water_year          INTEGER NOT NULL,
    month               INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    pumped_af           TEXT NOT NULL,
    PRIMARY KEY (well_id, water_year, month)
);

CREATE INDEX pumping_by_year ON well_pumping (water_year, well_id);
