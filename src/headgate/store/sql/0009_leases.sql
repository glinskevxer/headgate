-- One season's water moved between shareholders.

CREATE TABLE lease (
    number              TEXT PRIMARY KEY,
    water_year          INTEGER NOT NULL,
    lessor              INTEGER NOT NULL REFERENCES account(number),
    lessee              INTEGER NOT NULL REFERENCES account(number),
    source              TEXT NOT NULL,
    volume_af           TEXT NOT NULL,
    price_cents         INTEGER NOT NULL,
    offered_on          TEXT NOT NULL,
    status              TEXT NOT NULL,
    delivered_af        TEXT NOT NULL DEFAULT '0',
    note                TEXT NOT NULL DEFAULT '',
    CHECK (lessor <> lessee)
);

CREATE INDEX lease_by_year ON lease (water_year, number);
CREATE INDEX lease_by_lessor ON lease (lessor, water_year);
CREATE INDEX lease_by_lessee ON lease (lessee, water_year);
