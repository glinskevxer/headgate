-- Applications to change a right, and the terms they were approved on.

CREATE TABLE transfer_application (
    number              TEXT PRIMARY KEY,
    decree              TEXT NOT NULL REFERENCES water_right(decree),
    kind                TEXT NOT NULL,
    filed_on            TEXT NOT NULL,
    requested_af        TEXT NOT NULL,
    proved_af           TEXT NOT NULL,
    from_turnout        TEXT REFERENCES turnout(code),
    to_turnout          TEXT REFERENCES turnout(code),
    status              TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    approved_af         TEXT,
    return_flow_af      TEXT
);

CREATE INDEX transfer_by_decree ON transfer_application (decree);

CREATE TABLE transfer_dry_up (
    number              TEXT NOT NULL REFERENCES transfer_application(number),
    parcel_id           TEXT NOT NULL,
    offered             INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (number, parcel_id)
);

CREATE TABLE transfer_condition (
    number              TEXT NOT NULL REFERENCES transfer_application(number),
    ordinal             INTEGER NOT NULL,
    condition           TEXT NOT NULL,
    PRIMARY KEY (number, ordinal)
);
