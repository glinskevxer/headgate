"""The commands that build a district up in the first place.

A new book is empty and somebody has to type the canal into it. These are the
commands they use: the ditch, the turnouts on it, the shareholders and their
certificates, and the season the board declares each spring.

Adding a ditch reads the whole system, adds to it and writes it back, so the
shape is validated as a whole every time. A lateral that leaves a parent that
is not there is caught at the moment somebody types it rather than in July.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

import click

from ..assessment.payment import Payment, PaymentMethod
from ..assessment.tiers import Band, RateSchedule
from ..duty.requirement import gross_acre_feet
from ..errors import NotFoundError, PolicyError, ValidationError
from ..ids import AccountNumber, DitchCode, TurnoutCode
from ..model.account import Account, AccountStatus, ShareCertificate
from ..model.ditch import Ditch, DitchSystem, Turnout
from ..model.parcel import Application, CropCode, Parcel
from ..model.seepage import SeepageRun
from ..money import Money
from ..store.repo_accounts import (
    load_account,
    load_place_of_use,
    load_register,
    save_account,
    save_certificate,
    save_parcel,
    save_place_of_use,
)
from ..store.repo_ditch import load_system, save_system
from ..store.repo_payments import account_ledger, take_payment
from ..store.repo_schedule import adopt
from ..store.repo_season import declare_season
from ..store.repo_seepage import adopt_measured_rate, load_history, record_run
from ..wateryear import IrrigationSeason, parse_day
from .context import Context
from .render import field_list


def _system_or_empty(connection: sqlite3.Connection) -> DitchSystem | None:
    """The canal system, or nothing at all if the book has no ditches yet.

    Loading an empty system raises, because a district with no main canal is
    not a district. That is right everywhere except here, where the whole point
    is to be adding the first ditch.
    """

    try:
        return load_system(connection)
    except ValidationError:
        return None


@click.group()
def ditch() -> None:
    """Build the canal and the turnouts on it."""


@ditch.command("add")
@click.option("--code", required=True, help="Ditch code, such as MAIN or L2.")
@click.option("--name", required=True, help="What the map calls it.")
@click.option("--capacity", required=True, help="Capacity in cubic feet a second.")
@click.option("--length", required=True, help="Length in feet.")
@click.option("--loss", default="0.02", show_default=True, help="Loss as a fraction a mile.")
@click.option("--parent", default=None, help="The ditch this one leaves, for a lateral.")
@click.option("--offtake", default=None, help="Station on the parent where it leaves.")
@click.option("--diversion-mile", default=None, help="River mile, for the main canal.")
@click.pass_obj
def add_ditch(
    context: Context,
    code: str,
    name: str,
    capacity: str,
    length: str,
    loss: str,
    parent: str | None,
    offtake: str | None,
    diversion_mile: str | None,
) -> None:
    """Add a ditch to the system."""

    built = Ditch(
        code=DitchCode.parse(code),
        name=name,
        capacity_cfs=Decimal(capacity),
        length_feet=Decimal(length),
        loss_fraction_per_mile=Decimal(loss),
        parent=DitchCode.parse(parent) if parent is not None else None,
        offtake_station_feet=Decimal(offtake) if offtake is not None else None,
        diversion_mile=Decimal(diversion_mile) if diversion_mile is not None else None,
    )
    with context.open_current() as connection:
        existing = _system_or_empty(connection)
        ditches = (*existing.ditches, built) if existing is not None else (built,)
        save_system(connection, DitchSystem(ditches=ditches))
        click.echo(f"ditch {built.code} added, {built.length_miles:.2f} miles")


@ditch.command("turnout")
@click.option("--ditch", "ditch_code", required=True, help="The ditch it hangs off.")
@click.option("--code", required=True, help="Turnout code, such as L2-14.")
@click.option("--name", required=True, help="What the rider calls it.")
@click.option("--station", required=True, help="Feet down the ditch.")
@click.option("--capacity", required=True, help="Capacity in cubic feet a second.")
@click.option("--acres", default="0", show_default=True, help="Acres it serves.")
@click.pass_obj
def add_turnout(
    context: Context,
    ditch_code: str,
    code: str,
    name: str,
    station: str,
    capacity: str,
    acres: str,
) -> None:
    """Add a turnout to a ditch that is already there."""

    turnout = Turnout(
        code=TurnoutCode.parse(code),
        name=name,
        station_feet=Decimal(station),
        capacity_cfs=Decimal(capacity),
        served_acres=Decimal(acres),
    )
    with context.open_current() as connection:
        system = load_system(connection)
        target = system.ditch(DitchCode.parse(ditch_code))
        rebuilt = tuple(
            Ditch(
                code=item.code,
                name=item.name,
                capacity_cfs=item.capacity_cfs,
                length_feet=item.length_feet,
                loss_fraction_per_mile=item.loss_fraction_per_mile,
                turnouts=(*item.turnouts, turnout) if item.code == target.code else item.turnouts,
                parent=item.parent,
                offtake_station_feet=item.offtake_station_feet,
                diversion_mile=item.diversion_mile,
            )
            for item in system.ditches
        )
        save_system(connection, DitchSystem(ditches=rebuilt))
        click.echo(f"turnout {turnout.code} added to {target.code}")


@ditch.command("list")
@click.pass_obj
def list_ditches(context: Context) -> None:
    """List the ditches and how many turnouts are on each."""

    with context.open_current() as connection:
        system = _system_or_empty(connection)
        if system is None:
            click.echo("no ditches yet")
            return
        for item in system.ditches:
            parent = f" off {item.parent}" if item.parent is not None else " from the creek"
            click.echo(
                f"{item.code}  {item.name}{parent}, {item.length_miles:.2f} miles, "
                f"{len(item.turnouts)} turnouts"
            )


@ditch.command("seepage")
@click.option("--ditch", "ditch_code", required=True, help="Which ditch was run.")
@click.option("--on", "run_on", required=True, help="The day of the run.")
@click.option("--from-station", required=True, help="Station the upper flume sat at.")
@click.option("--to-station", required=True, help="Station the lower flume sat at.")
@click.option("--inflow", required=True, help="Upper flume, in cfs.")
@click.option("--outflow", required=True, help="Lower flume, in cfs.")
@click.option(
    "--turnouts", default="0", show_default=True, help="Water running to turnouts during the run."
)
@click.option("--error", default="0.05", show_default=True, help="What one flume may be out by.")
@click.option("--note", default="", help="Anything worth keeping with the run.")
@click.pass_obj
def seepage(
    context: Context,
    ditch_code: str,
    run_on: str,
    from_station: str,
    to_station: str,
    inflow: str,
    outflow: str,
    turnouts: str,
    error: str,
    note: str,
) -> None:
    """Record a seepage run down a reach of ditch."""

    run = SeepageRun(
        ditch=DitchCode.parse(ditch_code),
        run_on=parse_day(run_on),
        from_station_feet=Decimal(from_station),
        to_station_feet=Decimal(to_station),
        inflow_cfs=Decimal(inflow),
        outflow_cfs=Decimal(outflow),
        turnouts_running_cfs=Decimal(turnouts),
        flume_error_cfs=Decimal(error),
        note=note,
    )
    with context.open_current() as connection:
        record_run(connection, run)
    word = "gained" if run.is_gaining else "lost"
    click.echo(f"{run.ditch} {word} {abs(run.loss_cfs)} cfs over {run.length_miles:.2f} miles")
    for complaint in run.why_not():
        click.echo(f"  {complaint}")


@ditch.command("loss")
@click.option("--ditch", "ditch_code", required=True, help="Which ditch.")
@click.option("--adopt", is_flag=True, help="Put the measured rate on the ditch.")
@click.pass_obj
def loss(context: Context, ditch_code: str, adopt: bool) -> None:
    """What the runs say a ditch loses, and whether to believe them."""

    code = DitchCode.parse(ditch_code)
    with context.open_current() as connection:
        history = load_history(connection, code)
        if not history.runs:
            click.echo(f"nobody has run a seepage test on {code}")
            return
        standing = load_system(connection).ditch(code).loss_fraction_per_mile
        click.echo(
            field_list(
                [
                    ("ditch", str(code)),
                    ("runs", str(len(history.runs))),
                    ("credible", str(len(history.credible))),
                    ("gaining", str(len(history.gaining))),
                    ("on the book", f"{standing} a mile"),
                ]
            )
        )
        if not history.credible:
            click.echo("\nno run is worth setting a rate from")
            return
        measured = history.measured_loss_per_mile()
        click.echo(f"measured    {measured} a mile")
        if history.has_got_worse(standing):
            click.echo("\nthis ditch is losing more than the book says it does")
        if not adopt:
            return
        adopted = adopt_measured_rate(connection, code)
        click.echo(f"\n{code} now carries {adopted} a mile")


@click.group()
def account() -> None:
    """Shareholders and their certificates."""


@account.command("add")
@click.option("--number", required=True, help="Account number.")
@click.option("--name", required=True, help="Whose account it is.")
@click.option("--joined", required=True, help="The day they joined.")
@click.option("--mailing", multiple=True, help="A line of the mailing address.")
@click.pass_obj
def add_account(
    context: Context, number: str, name: str, joined: str, mailing: tuple[str, ...]
) -> None:
    """Add a shareholder account."""

    holder = Account(
        number=AccountNumber.parse(number),
        name=name,
        joined=parse_day(joined),
        status=AccountStatus.ACTIVE,
        mailing=tuple(mailing),
    )
    with context.open_current() as connection:
        save_account(connection, holder)
        click.echo(f"account {holder.number} added for {holder.name}")


@account.command("issue")
@click.option("--serial", required=True, help="Certificate serial, such as A-1001.")
@click.option("--account", "account_number", required=True, help="Who holds it.")
@click.option("--shares", required=True, help="How many shares.")
@click.option("--turnout", "turnout_code", required=True, help="Where they are delivered.")
@click.option("--issued", required=True, help="The day it was issued.")
@click.pass_obj
def issue_certificate(
    context: Context,
    serial: str,
    account_number: str,
    shares: str,
    turnout_code: str,
    issued: str,
) -> None:
    """Issue a share certificate out of the stock book."""

    certificate = ShareCertificate(
        serial=serial.upper(),
        account=AccountNumber.parse(account_number),
        shares=Decimal(shares),
        turnout=TurnoutCode.parse(turnout_code),
        issued=parse_day(issued),
    )
    with context.open_current() as connection:
        register = load_register(connection)
        register.issue(certificate)
        save_certificate(connection, certificate)
        click.echo(
            f"certificate {certificate.serial} issued to {certificate.account} for "
            f"{certificate.shares} shares at {certificate.turnout}"
        )


@account.command("pay")
@click.option("--account", "account_number", required=True, help="Who paid.")
@click.option("--amount", required=True, help="How much, in dollars.")
@click.option("--on", "received_on", required=True, help="The day it came in.")
@click.option(
    "--method",
    type=click.Choice([item.value for item in PaymentMethod]),
    default="cheque",
    show_default=True,
    help="How it arrived.",
)
@click.option("--reference", default="", help="Cheque number or anything like it.")
@click.pass_obj
def take(
    context: Context,
    account_number: str,
    amount: str,
    received_on: str,
    method: str,
    reference: str,
) -> None:
    """Take a payment against an account."""

    payment = Payment(
        account=AccountNumber.parse(account_number),
        received_on=parse_day(received_on),
        amount=Money.parse(amount),
        method=PaymentMethod(method),
        reference=reference,
    )
    with context.open_current() as connection:
        load_account(connection, payment.account)
        number = take_payment(connection, payment)
        ledger = account_ledger(connection, payment.account)
        click.echo(
            f"payment {number} of {payment.amount} taken, account {payment.account} owes "
            f"{ledger.balance}"
        )


@account.command("parcel")
@click.option("--parcel", "parcel_id", required=True, help="Assessor's parcel number.")
@click.option("--account", "account_number", required=True, help="Whose ground it is.")
@click.option("--turnout", "turnout_code", required=True, help="The gate it is served from.")
@click.option("--acres", required=True, help="Irrigated acres.")
@click.option(
    "--crop",
    type=click.Choice([item.value for item in CropCode]),
    default="alfalfa",
    show_default=True,
    help="What is growing on it.",
)
@click.option(
    "--application",
    "method",
    type=click.Choice([item.value for item in Application]),
    default="flood",
    show_default=True,
    help="How the water is put on.",
)
@click.option("--dried-up", default=None, help="The day it went out of production.")
@click.pass_obj
def add_parcel(
    context: Context,
    parcel_id: str,
    account_number: str,
    turnout_code: str,
    acres: str,
    crop: str,
    method: str,
    dried_up: str | None,
) -> None:
    """Put a parcel of ground under a turnout."""

    parcel = Parcel(
        parcel_id=parcel_id,
        account=AccountNumber.parse(account_number),
        turnout=TurnoutCode.parse(turnout_code),
        irrigated_acres=Decimal(acres),
        crop=CropCode(crop),
        application=Application(method),
        dried_up_on=parse_day(dried_up) if dried_up is not None else None,
    )
    with context.open_current() as connection:
        save_parcel(connection, parcel)
        needed = gross_acre_feet(parcel.crop, parcel.irrigated_acres, parcel.application)
        click.echo(
            f"parcel {parcel.parcel_id} added under {parcel.turnout}, "
            f"{parcel.irrigated_acres} acres of {parcel.crop.value} wanting "
            f"{needed:.2f} acre feet at the gate"
        )


@account.command("dry-up")
@click.option("--parcel", "parcel_id", required=True, help="Which parcel.")
@click.option("--on", "dried_on", required=True, help="The day it goes dry.")
@click.pass_obj
def dry_up(context: Context, parcel_id: str, dried_on: str) -> None:
    """Take a parcel out of production, which a transfer has to do."""

    with context.open_current() as connection:
        place = load_place_of_use(connection)
        dried = place.dry_up(parcel_id, parse_day(dried_on))
        save_place_of_use(connection, dried)
        click.echo(f"parcel {parcel_id} is dry from {dried_on}")


@account.command("list")
@click.option("--on", "as_of", default=None, help="The day to count shares as of.")
@click.pass_obj
def list_accounts(context: Context, as_of: str | None) -> None:
    """List the accounts and what they hold."""

    day = parse_day(as_of) if as_of is not None else date.today()
    with context.open_current() as connection:
        register = load_register(connection)
        if not register.accounts:
            click.echo("no accounts yet")
            return
        for holder in register.accounts:
            shares = register.shares_of(holder.number, day)
            click.echo(f"{holder.number}  {holder.name}  {shares} shares  {holder.status.value}")


@click.group()
def season() -> None:
    """Declare and look at the irrigation season."""


@season.command("declare")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--opens", required=True, help="The day the water goes on.")
@click.option("--closes", required=True, help="The day the water comes off.")
@click.option("--declared", required=True, help="The day the board voted.")
@click.option("--note", default="", help="Anything worth keeping with the vote.")
@click.pass_obj
def declare(
    context: Context, water_year: int, opens: str, closes: str, declared: str, note: str
) -> None:
    """Record the board's season declaration."""

    with context.open_current() as connection:
        declared_season = declare_season(
            connection,
            IrrigationSeason(water_year, parse_day(opens), parse_day(closes)),
            parse_day(declared),
            note,
        )
        click.echo(
            f"season {declared_season.water_year} declared, {declared_season.opened} to "
            f"{declared_season.closed}, {declared_season.length_days} days"
        )


@season.command("rates")
@click.option("--year", "water_year", required=True, type=int, help="Water year.")
@click.option("--per-share", required=True, help="Flat charge a share, in dollars.")
@click.option(
    "--band",
    multiple=True,
    help="A band as ceiling:rate, or open:rate for the top one.",
)
@click.option("--minimum", default="0", show_default=True, help="Minimum bill in dollars.")
@click.option("--adopted", required=True, help="The day the board adopted it.")
@click.pass_obj
def rates(
    context: Context,
    water_year: int,
    per_share: str,
    band: tuple[str, ...],
    minimum: str,
    adopted: str,
) -> None:
    """Adopt the rate schedule for a water year."""

    if not band:
        raise PolicyError("a schedule needs at least one band, the open one at the top")
    bands: list[Band] = []
    for text in band:
        ceiling, _, rate = text.partition(":")
        if not rate:
            raise PolicyError(f"{text!r} is not a band, write it as ceiling:rate")
        upper = None if ceiling.strip().lower() == "open" else Decimal(ceiling)
        bands.append(Band(upper_af=upper, rate_per_af=Money.parse(rate)))
    schedule = RateSchedule(
        water_year=water_year,
        per_share=Money.parse(per_share),
        bands=tuple(bands),
        minimum_bill=Money.parse(minimum),
    )
    with context.open_current() as connection:
        adopt(connection, schedule, parse_day(adopted))
        click.echo(
            f"{water_year} rates adopted, {schedule.per_share} a share and "
            f"{len(schedule.bands)} bands"
        )


def register_commands(group: click.Group) -> None:
    """Hang the setup commands off the main group."""

    from .close import register as register_close
    from .restate import register as register_restate

    register_close(season)
    register_restate(season)
    group.add_command(ditch)
    group.add_command(account)
    group.add_command(season)


def require_turnout(context: Context, code: str) -> TurnoutCode:
    """Check a turnout exists before something else leans on it."""

    turnout = TurnoutCode.parse(code)
    with context.open_current() as connection:
        try:
            load_system(connection).find_turnout(turnout)
        except NotFoundError as exc:
            raise PolicyError(f"there is no turnout {turnout} on this system") from exc
    return turnout
