-- The journal, and the assessment bills that get posted to it.

CREATE TABLE journal_entry (
    sequence            INTEGER PRIMARY KEY,
    recorded_at         TEXT NOT NULL,
    kind                TEXT NOT NULL,
    subject             TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    volume_af           TEXT,
    amount_cents        INTEGER,
    reverses            INTEGER REFERENCES journal_entry(sequence),
    CHECK (reverses IS NULL OR reverses < sequence)
);

CREATE INDEX journal_by_subject ON journal_entry (subject, sequence);
CREATE INDEX journal_by_kind ON journal_entry (kind, sequence);

CREATE TABLE assessment_bill (
    bill_id             INTEGER PRIMARY KEY,
    water_year          INTEGER NOT NULL,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    issued_on           TEXT NOT NULL,
    reverses_bill_id    INTEGER REFERENCES assessment_bill(bill_id),
    note                TEXT NOT NULL DEFAULT ''
);

CREATE INDEX bill_by_account ON assessment_bill (account_number, water_year);

CREATE TABLE assessment_line (
    bill_id             INTEGER NOT NULL REFERENCES assessment_bill(bill_id),
    line_number         INTEGER NOT NULL,
    kind                TEXT NOT NULL,
    description         TEXT NOT NULL,
    quantity            TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL,
    PRIMARY KEY (bill_id, line_number)
);
