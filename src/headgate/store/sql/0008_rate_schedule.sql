-- The rate schedule the board adopts each spring.

CREATE TABLE rate_schedule (
    water_year          INTEGER PRIMARY KEY,
    per_share_cents     INTEGER NOT NULL,
    minimum_bill_cents  INTEGER NOT NULL DEFAULT 0,
    adopted_on          TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT ''
);

CREATE TABLE rate_band (
    water_year          INTEGER NOT NULL REFERENCES rate_schedule(water_year),
    ordinal             INTEGER NOT NULL,
    upper_af            TEXT,
    rate_cents_per_af   INTEGER NOT NULL,
    PRIMARY KEY (water_year, ordinal)
);
