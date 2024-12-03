-- Money coming in against the assessment.

CREATE TABLE payment (
    payment_id          INTEGER PRIMARY KEY,
    account_number      INTEGER NOT NULL REFERENCES account(number),
    received_on         TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL CHECK (amount_cents > 0),
    method              TEXT NOT NULL,
    reference           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX payment_by_account ON payment (account_number, received_on);
