-- Orders, the notices that hold them down, and the rotation they run under.

CREATE TABLE water_order (
    order_id            INTEGER PRIMARY KEY,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    turnout_code        TEXT NOT NULL REFERENCES turnout(code),
    requested_cfs       TEXT NOT NULL,
    run_from            TEXT NOT NULL,
    run_to              TEXT NOT NULL,
    placed_at           TEXT NOT NULL,
    status              TEXT NOT NULL,
    allowed_cfs         TEXT,
    note                TEXT NOT NULL DEFAULT '',
    CHECK (run_to > run_from)
);

CREATE INDEX water_order_by_turnout ON water_order (turnout_code, run_from);
CREATE INDEX water_order_by_account ON water_order (account_number);

CREATE TABLE curtailment_notice (
    decree              TEXT NOT NULL REFERENCES water_right(decree),
    called_by           TEXT NOT NULL REFERENCES water_right(decree),
    issued_at           TEXT NOT NULL,
    effective_at        TEXT NOT NULL,
    curtailed_cfs       TEXT NOT NULL,
    allowed_cfs         TEXT NOT NULL,
    reason              TEXT NOT NULL,
    lifted_at           TEXT,
    PRIMARY KEY (decree, called_by, issued_at)
);

CREATE INDEX curtailment_by_effect ON curtailment_notice (effective_at);

CREATE TABLE rotation_window (
    water_year          INTEGER NOT NULL,
    turnout_code        TEXT NOT NULL REFERENCES turnout(code),
    run_from            TEXT NOT NULL,
    run_to              TEXT NOT NULL,
    rate_cfs            TEXT NOT NULL,
    PRIMARY KEY (turnout_code, run_from),
    CHECK (run_to > run_from)
);

CREATE INDEX rotation_by_year ON rotation_window (water_year, run_from);
