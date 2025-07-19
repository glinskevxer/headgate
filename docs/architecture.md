# how headgate is put together

Four layers, and the dependencies only ever point one way: down.

## the domain

`model`, `rating`, `measure`, `priority`, `carriage`, `rotation`, `orders`,
`duty`, `transfer`, `assessment`, `storage`, `lease`, `wells`, `forecast`.

These know about water and nothing else. No module in here imports `store` or
`cli`, so every rule can be tested by handing it values, and none of them can
be accidentally coupled to a table. Everything is frozen dataclasses and
functions that return new values, which is why a season can be re-worked
against a corrected calibration without touching what the book already said.

The `Decimal` discipline lives here too. Volumes are acre feet to four places,
rates are cubic feet a second to three, money is whole cents, and nothing in
the package converts any of them to a float. The one exception is the well
depletion model, which is an error function over an aquifer and says so.

## the store

`store` owns the SQLite file and is the only layer that knows SQL exists. One
module per subject, each with the same shape: a `_thing_from(row)` mapper, a
`save_thing`, a `load_thing`, and whatever queries the reports need. Nothing in
`store` decides anything; it reads and writes what the domain hands it and
raises `StoreError` when the file says something the domain could not have
written.

`store.assemble` is the seam between the two. It is the one place that knows
both how to read rows and what a `DeliveryLedger` is, which keeps that
knowledge out of both the domain and the repositories.

## the command line

`cli` builds the arguments into domain values, calls the domain, and prints.
A command that has a decision in it is a command with a bug: the decision
belongs in the domain where it can be tested without a terminal. The group
turns a `HeadgateError` into a click error, so a deliberate refusal reads the
way click's own errors read and exits non zero for a shell script.

## the tools

`tools` are programs the build runs, not things a district runs: the migration
checker, the docs and schema generators, the coverage gate, the smoke run.
They exist so that a change which breaks something the tests do not cover
still fails in the build.

## why the book is append only

Deliveries, journal entries, bills, notices and certificates are never edited.
A wrong one is answered: a reversal, a restatement, a lift, a retirement. It
costs rows and it buys the only thing that matters when a season is argued
about two years later, which is being able to say what the district believed at
the time and what it did about it afterwards.
