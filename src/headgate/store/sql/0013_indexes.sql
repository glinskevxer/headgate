-- Indexes for the queries the office runs every day.

CREATE INDEX water_order_by_status ON water_order (status, run_from);
CREATE INDEX journal_by_time ON journal_entry (recorded_at, sequence);
CREATE INDEX bill_by_year ON assessment_bill (water_year, account_number);
CREATE INDEX payment_by_day ON payment (received_on);
CREATE INDEX certificate_outstanding ON certificate (retired, turnout_code);
CREATE INDEX device_by_ditch ON device (ditch_code);
