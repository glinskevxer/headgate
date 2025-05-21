-- How the water is put on each parcel, which decides what it needs at the gate.

ALTER TABLE parcel ADD COLUMN application TEXT NOT NULL DEFAULT 'flood';

CREATE INDEX parcel_by_account ON parcel (account_number);
