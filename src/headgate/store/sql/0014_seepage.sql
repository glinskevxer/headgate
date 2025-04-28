-- Seepage runs: what a ditch was measured to lose, and when.

CREATE TABLE seepage_run (
    ditch_code          TEXT NOT NULL REFERENCES ditch(code),
    run_on              TEXT NOT NULL,
    from_station_feet   TEXT NOT NULL,
    to_station_feet     TEXT NOT NULL,
    inflow_cfs          TEXT NOT NULL,
    outflow_cfs         TEXT NOT NULL,
    turnouts_cfs        TEXT NOT NULL DEFAULT '0',
    flume_error_cfs     TEXT NOT NULL DEFAULT '0.05',
    note                TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (ditch_code, run_on, from_station_feet)
);

CREATE INDEX seepage_by_ditch ON seepage_run (ditch_code, run_on);
