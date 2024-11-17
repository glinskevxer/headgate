-- The reservoir, what is in it, and whose water that is.

CREATE TABLE reservoir (
    name                TEXT PRIMARY KEY,
    decree              TEXT NOT NULL REFERENCES water_right(decree),
    capacity_af         TEXT NOT NULL,
    dead_pool_af        TEXT NOT NULL,
    fill_opens_month    INTEGER NOT NULL,
    fill_opens_day      INTEGER NOT NULL,
    fill_closes_month   INTEGER NOT NULL,
    fill_closes_day     INTEGER NOT NULL
);

CREATE TABLE pool_state (
    reservoir_name      TEXT NOT NULL REFERENCES reservoir(name),
    water_year          INTEGER NOT NULL,
    contents_af         TEXT NOT NULL,
    filled_af           TEXT NOT NULL DEFAULT '0',
    spilled_af          TEXT NOT NULL DEFAULT '0',
    released_af         TEXT NOT NULL DEFAULT '0',
    fill_finished       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (reservoir_name, water_year)
);

CREATE TABLE storage_entry (
    reservoir_name      TEXT NOT NULL REFERENCES reservoir(name),
    water_year          INTEGER NOT NULL,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    shares              TEXT NOT NULL,
    allocated_af        TEXT NOT NULL,
    released_af         TEXT NOT NULL DEFAULT '0',
    spilled_af          TEXT NOT NULL DEFAULT '0',
    carried_in_af       TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (reservoir_name, water_year, account_number)
);

CREATE INDEX storage_by_account ON storage_entry (account_number, water_year);
