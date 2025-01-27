# headgate commands

This file is generated from the command line by `python -m headgate.tools.build_docs`. Do not edit it by hand.

## headgate account

Shareholders and their certificates.

## headgate account add

Add a shareholder account.

- `--number` (required) Account number.
- `--name` (required) Whose account it is.
- `--joined` (required) The day they joined.
- `--mailing` A line of the mailing address.

## headgate account issue

Issue a share certificate out of the stock book.

- `--serial` (required) Certificate serial, such as A-1001.
- `--account` (required) Who holds it.
- `--shares` (required) How many shares.
- `--turnout` (required) Where they are delivered.
- `--issued` (required) The day it was issued.

## headgate account list

List the accounts and what they hold.

- `--on` The day to count shares as of.

## headgate account pay

Take a payment against an account.

- `--account` (required) Who paid.
- `--amount` (required) How much, in dollars.
- `--on` (required) The day it came in.
- `--method` How it arrived.
- `--reference` Cheque number or anything like it.

## headgate call

Calls on the stream, and the notices that answer them.

## headgate call lift

Lift every notice served for one call.

- `--decree` (required) The right whose call is over.
- `--at` When it was lifted.

## headgate call place

Work a call against the creek as it stands.

- `--decree` (required) The right placing the call.
- `--arriving` (required) What is reaching its headgate, in cfs.
- `--taking` A diversion as decree=cfs.
- `--at` When the call was placed.
- `--needed-by` When the water has to be there.
- `--stream` The stream's name.
- `--serve` Serve the notices if it is honoured.
- `--notice-hours` Notice period.

## headgate call standing

What curtailments are in force.

- `--at` The moment to look at.

## headgate check

Read the book over and say what is wrong with it.

- `--on` The day to check against, default today.
- `--warnings` Print the warnings as well as the problems.
- `--list-checks` Print what gets checked and stop.

## headgate device

Structures, their staff gauges and their calibrations.

## headgate device calibrate

Record a field check against a current meter.

- `--tag` (required) Device tag.
- `--on` (required) The day it was checked.
- `--by` (required) Who checked it.
- `--offset` Staff offset in feet.
- `--months` How long the check stands.
- `--note` Anything worth keeping with the check.

## headgate device install

Put a structure in the ditch.

- `--tag` (required) Device tag, such as WEIR-L2-14.
- `--kind` (required) What it is.
- `--installed` (required) The day it went in.
- `--turnout` Turnout it sits in.
- `--ditch` Ditch it sits on.
- `--crest` Crest width in feet, for a weir.
- `--throat` Throat width in feet, for a flume or orifice.
- `--opening` Opening height in feet, for an orifice.
- `--contractions` End contractions on a weir.

## headgate device lapsed

Devices in the ditch with no calibration standing.

- `--on` The day to check.

## headgate device list

List the devices and whether their calibration still stands.

- `--on` The day to report as of.

## headgate device show

What a device is, and what rating it reads against.

- `tag` (argument)
- `--on` The day to read it against.

## headgate ditch

Build the canal and the turnouts on it.

## headgate ditch add

Add a ditch to the system.

- `--code` (required) Ditch code, such as MAIN or L2.
- `--name` (required) What the map calls it.
- `--capacity` (required) Capacity in cubic feet a second.
- `--length` (required) Length in feet.
- `--loss` Loss as a fraction a mile.
- `--parent` The ditch this one leaves, for a lateral.
- `--offtake` Station on the parent where it leaves.
- `--diversion-mile` River mile, for the main canal.

## headgate ditch list

List the ditches and how many turnouts are on each.

## headgate ditch turnout

Add a turnout to a ditch that is already there.

- `--ditch` (required) The ditch it hangs off.
- `--code` (required) Turnout code, such as L2-14.
- `--name` (required) What the rider calls it.
- `--station` (required) Feet down the ditch.
- `--capacity` (required) Capacity in cubic feet a second.
- `--acres` Acres it serves.

## headgate init

Set up a new district book.

- `--name` (required) The district's name.
- `--state` (required) Two letter state code.
- `--stream` (required) The stream the main canal heads on.
- `--miners-inch` Which statute the district converts miner's inches under.

## headgate migrate-book

Bring an existing book up to this version.

## headgate order

Take and answer orders for water.

## headgate order answer

Answer a waiting order against the book as it stands.

- `order_id` (argument)
- `--curtailed-to` Rate a standing curtailment allows.
- `--notice-hours` Override the district's notice period.

## headgate order cancel

Cancel an order that is not going to run.

- `order_id` (argument)
- `--note` Why it was cancelled.

## headgate order list

List the orders in the book.

- `--waiting` Only orders not yet answered.

## headgate order place

Take an order and leave it waiting for an answer.

- `--account` (required) Shareholder account number.
- `--turnout` (required) Turnout the water runs to.
- `--rate` (required) Rate asked for, in cubic feet a second.
- `--from` (required) When the run starts.
- `--to` (required) When the run ends.
- `--placed` When the order was taken, if not now.

## headgate reading

Staff readings and meter totals.

## headgate reading add

Write one reading and say what it means.

- `--device` (required) Device tag.
- `--at` (required) When it was read.
- `--by` (required) Who read it.
- `--head` Gauge height in feet.
- `--tail` Tailwater in feet, for a flume.
- `--total` Meter total in acre feet.
- `--note` Anything worth keeping with the reading.

## headgate reading import

Load a file of readings, all of it or none of it.

- `path` (argument)
- `--dry-run` Check the file and write nothing.

## headgate reading list

Every reading on one device, oldest first.

- `device_tag` (argument)

## headgate report

Print what the book says.

## headgate report gaps

Turnouts nothing is measuring, and turnouts with holes in the record.

- `water_year` (argument)

## headgate report journal

Print the journal, or the part of it somebody asked about.

- `--subject` Only entries about one subject.
- `--kind` Only entries of one kind.
- `--from` Earliest entry to print.
- `--to` Latest entry to print.

## headgate report running

What is running right now, off the answered orders.

- `--at` The moment to look at, default now.

## headgate report season

The season report, headgate to turnout.

- `water_year` (argument)
- `--loss` How the ditch loss is charged out.

## headgate report turnout

One turnout's record over a span, segment by segment.

- `turnout_code` (argument)
- `--from` (required) Start of the span to report.
- `--to` (required) End of the span to report.

## headgate reservoir

The reservoir, the pool and the storage accounts.

## headgate reservoir allocate

Split the usable pool between the shareholders.

- `--name` (required) Which reservoir.
- `--year` (required) Water year.
- `--on` (required) The day the shares are counted on.

## headgate reservoir build

Put a reservoir in the book.

- `--name` (required) What the reservoir is called.
- `--decree` (required) The storage right that fills it.
- `--capacity` (required) Capacity in acre feet.
- `--dead-pool` Acre feet below the outlet.

## headgate reservoir draw

Release water against one account's storage.

- `--name` (required) Which reservoir.
- `--year` (required) Water year.
- `--account` (required) Whose water it is.
- `--volume` (required) Acre feet to release.

## headgate reservoir fill

Store a day's inflow, spilling what will not fit.

- `--name` (required) Which reservoir.
- `--on` (required) The day the water came in.
- `--inflow` (required) Acre feet stored that day.

## headgate reservoir show

The pool and the accounts behind it.

- `--name` (required) Which reservoir.
- `--year` (required) Water year.

## headgate season

Declare and look at the irrigation season.

## headgate season close

Close a season: total the water, charge the loss, bill everybody.

- `--year` (required) Water year to close.
- `--issued` The day the bills go out, default today.
- `--loss` How the ditch loss is charged out.
- `--dry-run` Work the numbers and write nothing.

## headgate season declare

Record the board's season declaration.

- `--year` (required) Water year.
- `--opens` (required) The day the water goes on.
- `--closes` (required) The day the water comes off.
- `--declared` (required) The day the board voted.
- `--note` Anything worth keeping with the vote.

## headgate season rates

Adopt the rate schedule for a water year.

- `--year` (required) Water year.
- `--per-share` (required) Flat charge a share, in dollars.
- `--band` A band as ceiling:rate, or open:rate for the top one.
- `--minimum` Minimum bill in dollars.
- `--adopted` (required) The day the board adopted it.

## headgate status

Say what book this is and where it stands.

## headgate transfer

Applications to change a right.

## headgate transfer approve

Approve an application on terms.

- `number` (argument)
- `--approved` (required) Acre feet the terms allow.
- `--consumed-share` (required) Share of the delivery consumed.
- `--condition` A condition of the approval.

## headgate transfer deny

Deny an application.

- `number` (argument)
- `--reason` (required) Why it was denied.

## headgate transfer file

File an application against a right.

- `--number` (required) Application number.
- `--decree` (required) The right being changed.
- `--kind` (required) What changes.
- `--filed` (required) The day it was filed.
- `--requested` (required) Acre feet asked to be moved.
- `--proved` (required) Acre feet the study proves.
- `--from-turnout` Where the water comes off.
- `--to-turnout` Where it is going.
- `--dry-up` A parcel offered for dry up.

## headgate transfer list

List the applications in the book.

- `--decree` Only applications against one right.
- `--open` Only the ones still moving.

## headgate transfer protest

Record a protest against a published application.

- `number` (argument)
- `--note` (required) What the protest says.

## headgate transfer publish

Publish an application for protest.

- `number` (argument)
