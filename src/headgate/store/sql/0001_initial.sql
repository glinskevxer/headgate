-- The district itself, the ditches it runs and the people it delivers to.

CREATE TABLE district (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    name                TEXT NOT NULL,
    state_code          TEXT NOT NULL,
    miners_inch_standard TEXT NOT NULL,
    stream_name         TEXT NOT NULL
);

CREATE TABLE reach (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    head_mile           TEXT NOT NULL,
    toe_mile            TEXT NOT NULL,
    mean_velocity_fps   TEXT NOT NULL,
    loss_per_mile       TEXT NOT NULL
);

CREATE TABLE ditch (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    capacity_cfs        TEXT NOT NULL,
    length_feet         TEXT NOT NULL,
    loss_per_mile       TEXT NOT NULL,
    parent_code         TEXT REFERENCES ditch(code),
    offtake_station_feet TEXT,
    diversion_mile      TEXT,
    CHECK ((parent_code IS NULL) = (offtake_station_feet IS NULL))
);

CREATE TABLE turnout (
    code                TEXT PRIMARY KEY,
    ditch_code          TEXT NOT NULL REFERENCES ditch(code),
    name                TEXT NOT NULL,
    station_feet        TEXT NOT NULL,
    capacity_cfs        TEXT NOT NULL,
    served_acres        TEXT NOT NULL
);

CREATE INDEX turnout_by_ditch ON turnout (ditch_code);

CREATE TABLE account (
    number              INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    joined              TEXT NOT NULL,
    status              TEXT NOT NULL,
    mailing             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE certificate (
    serial              TEXT PRIMARY KEY,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    shares              TEXT NOT NULL,
    turnout_code        TEXT NOT NULL REFERENCES turnout(code),
    issued              TEXT NOT NULL,
    retired             TEXT
);

CREATE INDEX certificate_by_account ON certificate (account_number);
CREATE INDEX certificate_by_turnout ON certificate (turnout_code);

CREATE TABLE parcel (
    parcel_id           TEXT PRIMARY KEY,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    turnout_code        TEXT NOT NULL REFERENCES turnout(code),
    irrigated_acres     TEXT NOT NULL,
    crop                TEXT NOT NULL,
    dried_up_on         TEXT
);

CREATE INDEX parcel_by_turnout ON parcel (turnout_code);
