-- The allotment a share is worth in a rationed year, and what each account used.

CREATE TABLE allotment (
    water_year          INTEGER NOT NULL,
    revision            INTEGER NOT NULL,
    af_per_share        TEXT NOT NULL,
    set_on              TEXT NOT NULL,
    basis               TEXT NOT NULL,
    PRIMARY KEY (water_year, revision)
);

CREATE TABLE allotment_use (
    water_year          INTEGER NOT NULL,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    shares              TEXT NOT NULL,
    used_af             TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (water_year, account_number)
);
