# headgate

Water accounting for a ditch company. It keeps the delivery record for a
canal system, administers priority calls against the decrees on the stream,
and bills the annual assessment off the season that was actually delivered.

Everything is a command line tool over a SQLite file. There is no server.

    headgate season open 2025
    headgate order place --account 118 --turnout L2-14 --rate 1.4
    headgate reading add --device WEIR-L2-14 --gauge 0.62
    headgate report season 2025

Volumes are acre feet and rates are cubic feet per second. Miner's inches are
accepted on input where a district still uses them, and are converted on the
way in against the statutory standard for the state the ditch sits in.
