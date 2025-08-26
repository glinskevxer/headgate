# headgate

Water accounting for a ditch company. It keeps the delivery record for a canal
system, administers priority calls against the decrees on the stream, rations a
short year, and bills the annual assessment off the season that was actually
delivered.

Everything is a command line tool over one SQLite file. There is no server and
there is nothing to install on a rider's tablet.

    headgate init --name "Sanpete Ditch Company" --state ut --stream "Sanpete Creek"
    headgate ditch add --code MAIN --name "Sanpete Main Canal" --capacity 48 \
        --length 26400 --diversion-mile 28.4
    headgate season declare --year 2025 --opens 2025-04-15 --closes 2025-10-01 \
        --declared 2025-03-20
    headgate reading import april-riders-book.csv
    headgate report season 2025
    headgate season close --year 2025 --issued 2025-11-01

## What it is careful about

**Where the water went, and how well anybody knows.** Every delivery carries
its provenance. A reading taken on a calibrated device inside its rated range
is measured. One taken on a device whose check lapsed in June, or past the end
of the rating, or eyeballed by a rider in a hurry, is an estimate: the water
still gets billed and it is no longer evidence. A drowned flume or a device
that was out of the ditch produces no number at all. That distinction runs all
the way through to the historical consumptive use a transfer is limited to, so
a lapsed calibration in 2019 is a smaller transfer in 2025.

**The order rights are administered in.** A call by a senior right shuts
juniors from the bottom up, but only the ones above the calling point, only as
far as the carriage loss between them allows, and only if the water gets there
in time to be any use. A call that cannot be usefully answered is refused as
futile rather than half honoured, because the juniors would be dried up for
nothing.

**Money that ties to water.** The assessment is billed off the same ledger the
season report is built from, so the two cannot disagree. A device found to have
been reading high does not get its record edited: the season is restated, the
old bill is reversed, a new one is issued, and all three sit in the file with
the arithmetic between them.

## What is in it

    headgate ditch      the canal, its laterals and the turnouts on them
    headgate stream     the creek, reach by reach
    headgate right      the decrees and the ladder they are administered in
    headgate account    shareholders, certificates, parcels and payments
    headgate device     structures, their ratings and their calibrations
    headgate reading    staff readings, a rider's file, a datalogger's file
    headgate order      taking orders, answering them, cutting a short day
    headgate call       placing a call, serving notices, lifting them
    headgate rotation   taking turns when there is not enough to go round
    headgate allotment  what a share is worth in a rationed year
    headgate reservoir  the pool, the storage accounts and the carryover
    headgate lease      moving this year's water between shareholders
    headgate transfer   moving a right for good, on terms
    headgate well       supplemental wells and what they take out of the creek
    headgate gage       the gaging record on the creek
    headgate season     declaring it, rating it, closing it, restating it
    headgate report     everything the office and the board read
    headgate check      what is wrong with the book, before somebody finds out

## Units

Volumes are acre feet and rates are cubic feet per second, both carried as
decimals. Miner's inches are accepted on input where a district still uses
them, converted against the statute for the state the ditch sits under, which
is not the same fraction everywhere.

## Running it

Python 3.12 or newer, and click. The development extra pins the test and lint
toolchain exactly:

    python -m pip install -e ".[dev]"
    python -m pytest -q
    python -m ruff check .
    python -m mypy

`docs/commands.md` is the command reference and `docs/schema.md` is the
schema; both are generated and both are checked in the build, so neither can
drift from the code.
