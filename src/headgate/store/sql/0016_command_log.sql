-- What was run against this book, by whom, and whether it worked.

CREATE TABLE command_log (
    entry_id            INTEGER PRIMARY KEY,
    ran_at              TEXT NOT NULL,
    operator            TEXT NOT NULL,
    command             TEXT NOT NULL,
    arguments           TEXT NOT NULL DEFAULT '',
    outcome             TEXT NOT NULL
);

CREATE INDEX command_log_by_time ON command_log (ran_at, entry_id);
CREATE INDEX command_log_by_command ON command_log (command, ran_at);
