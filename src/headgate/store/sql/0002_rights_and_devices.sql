-- Decreed rights, the structures that measure water, and the seasons.

CREATE TABLE water_right (
    decree              TEXT PRIMARY KEY,
    owner               TEXT NOT NULL,
    kind                TEXT NOT NULL,
    appropriation_date  TEXT NOT NULL,
    adjudication_year   INTEGER NOT NULL,
    sequence_number     INTEGER NOT NULL,
    diversion_mile      TEXT NOT NULL,
    rate_cfs            TEXT,
    volume_af           TEXT,
    ditch_code          TEXT REFERENCES ditch(code),
    status              TEXT NOT NULL,
    CHECK (rate_cfs IS NOT NULL OR volume_af IS NOT NULL)
);

CREATE INDEX right_by_priority ON water_right (appropriation_date, sequence_number);

CREATE TABLE device (
    tag                 TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    installed           TEXT NOT NULL,
    removed             TEXT,
    crest_width_feet    TEXT,
    throat_width_feet   TEXT,
    opening_height_feet TEXT,
    end_contractions    INTEGER NOT NULL DEFAULT 0,
    min_head_feet       TEXT NOT NULL,
    max_head_feet       TEXT NOT NULL,
    turnout_code        TEXT REFERENCES turnout(code),
    ditch_code          TEXT REFERENCES ditch(code),
    CHECK ((turnout_code IS NULL) <> (ditch_code IS NULL))
);

CREATE INDEX device_by_turnout ON device (turnout_code);

CREATE TABLE calibration (
    device_tag          TEXT NOT NULL REFERENCES device(tag),
    performed           TEXT NOT NULL,
    performed_by        TEXT NOT NULL,
    expires             TEXT NOT NULL,
    staff_offset_feet   TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device_tag, performed)
);

CREATE TABLE reading (
    device_tag          TEXT NOT NULL REFERENCES device(tag),
    taken_at            TEXT NOT NULL,
    observer            TEXT NOT NULL,
    method              TEXT NOT NULL,
    head_feet           TEXT,
    tail_feet           TEXT,
    meter_total_af      TEXT,
    note                TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device_tag, taken_at)
);

CREATE INDEX reading_by_time ON reading (taken_at);

CREATE TABLE season (
    water_year          INTEGER PRIMARY KEY,
    opened              TEXT NOT NULL,
    closed              TEXT NOT NULL,
    declared_on         TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT ''
);
