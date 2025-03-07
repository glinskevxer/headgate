-- The gaging record on the creek.

CREATE TABLE gage (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    river_mile          TEXT NOT NULL,
    datum_feet          TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE gage_day (
    gage_code           TEXT NOT NULL REFERENCES gage(code),
    day                 TEXT NOT NULL,
    mean_cfs            TEXT NOT NULL,
    grade               TEXT NOT NULL,
    PRIMARY KEY (gage_code, day)
);

CREATE INDEX gage_day_by_day ON gage_day (day);
