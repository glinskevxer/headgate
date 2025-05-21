# headgate schema

This file is generated from the migrations by `python -m headgate.tools.schema_dump`. Do not edit it by hand.

## account

- `number` INTEGER (key)
- `name` TEXT (not null)
- `joined` TEXT (not null)
- `status` TEXT (not null)
- `mailing` TEXT (not null)

## allotment

- `water_year` INTEGER (key, not null)
- `revision` INTEGER (key, not null)
- `af_per_share` TEXT (not null)
- `set_on` TEXT (not null)
- `basis` TEXT (not null)

## allotment_use

- `water_year` INTEGER (key, not null)
- `account_number` INTEGER (key, not null)
- `shares` TEXT (not null)
- `used_af` TEXT (not null)

## assessment_bill

- `bill_id` INTEGER (key)
- `water_year` INTEGER (not null)
- `account_number` INTEGER (not null)
- `issued_on` TEXT (not null)
- `reverses_bill_id` INTEGER
- `note` TEXT (not null)

indexes: `bill_by_account`, `bill_by_year`

## assessment_line

- `bill_id` INTEGER (key, not null)
- `line_number` INTEGER (key, not null)
- `kind` TEXT (not null)
- `description` TEXT (not null)
- `quantity` TEXT (not null)
- `amount_cents` INTEGER (not null)

## calibration

- `device_tag` TEXT (key, not null)
- `performed` TEXT (key, not null)
- `performed_by` TEXT (not null)
- `expires` TEXT (not null)
- `staff_offset_feet` TEXT (not null)
- `note` TEXT (not null)

## certificate

- `serial` TEXT (key)
- `account_number` INTEGER (not null)
- `shares` TEXT (not null)
- `turnout_code` TEXT (not null)
- `issued` TEXT (not null)
- `retired` TEXT

indexes: `certificate_by_account`, `certificate_by_turnout`, `certificate_outstanding`

## curtailment_notice

- `decree` TEXT (key, not null)
- `called_by` TEXT (key, not null)
- `issued_at` TEXT (key, not null)
- `effective_at` TEXT (not null)
- `curtailed_cfs` TEXT (not null)
- `allowed_cfs` TEXT (not null)
- `reason` TEXT (not null)
- `lifted_at` TEXT

indexes: `curtailment_by_effect`

## device

- `tag` TEXT (key)
- `kind` TEXT (not null)
- `installed` TEXT (not null)
- `removed` TEXT
- `crest_width_feet` TEXT
- `throat_width_feet` TEXT
- `opening_height_feet` TEXT
- `end_contractions` INTEGER (not null)
- `min_head_feet` TEXT (not null)
- `max_head_feet` TEXT (not null)
- `turnout_code` TEXT
- `ditch_code` TEXT

indexes: `device_by_ditch`, `device_by_turnout`

## district

- `id` INTEGER (key)
- `name` TEXT (not null)
- `state_code` TEXT (not null)
- `miners_inch_standard` TEXT (not null)
- `stream_name` TEXT (not null)

## ditch

- `code` TEXT (key)
- `name` TEXT (not null)
- `capacity_cfs` TEXT (not null)
- `length_feet` TEXT (not null)
- `loss_per_mile` TEXT (not null)
- `parent_code` TEXT
- `offtake_station_feet` TEXT
- `diversion_mile` TEXT

## gage

- `code` TEXT (key)
- `name` TEXT (not null)
- `river_mile` TEXT (not null)
- `datum_feet` TEXT (not null)

## gage_day

- `gage_code` TEXT (key, not null)
- `day` TEXT (key, not null)
- `mean_cfs` TEXT (not null)
- `grade` TEXT (not null)

indexes: `gage_day_by_day`

## journal_entry

- `sequence` INTEGER (key)
- `recorded_at` TEXT (not null)
- `kind` TEXT (not null)
- `subject` TEXT (not null)
- `note` TEXT (not null)
- `volume_af` TEXT
- `amount_cents` INTEGER
- `reverses` INTEGER

indexes: `journal_by_kind`, `journal_by_subject`, `journal_by_time`

## lease

- `number` TEXT (key)
- `water_year` INTEGER (not null)
- `lessor` INTEGER (not null)
- `lessee` INTEGER (not null)
- `source` TEXT (not null)
- `volume_af` TEXT (not null)
- `price_cents` INTEGER (not null)
- `offered_on` TEXT (not null)
- `status` TEXT (not null)
- `delivered_af` TEXT (not null)
- `note` TEXT (not null)

indexes: `lease_by_lessee`, `lease_by_lessor`, `lease_by_year`

## parcel

- `parcel_id` TEXT (key)
- `account_number` INTEGER (not null)
- `turnout_code` TEXT (not null)
- `irrigated_acres` TEXT (not null)
- `crop` TEXT (not null)
- `dried_up_on` TEXT
- `application` TEXT (not null)

indexes: `parcel_by_account`, `parcel_by_turnout`

## payment

- `payment_id` INTEGER (key)
- `account_number` INTEGER (not null)
- `received_on` TEXT (not null)
- `amount_cents` INTEGER (not null)
- `method` TEXT (not null)
- `reference` TEXT (not null)

indexes: `payment_by_account`, `payment_by_day`

## pool_state

- `reservoir_name` TEXT (key, not null)
- `water_year` INTEGER (key, not null)
- `contents_af` TEXT (not null)
- `filled_af` TEXT (not null)
- `spilled_af` TEXT (not null)
- `released_af` TEXT (not null)
- `fill_finished` INTEGER (not null)

## rate_band

- `water_year` INTEGER (key, not null)
- `ordinal` INTEGER (key, not null)
- `upper_af` TEXT
- `rate_cents_per_af` INTEGER (not null)

## rate_schedule

- `water_year` INTEGER (key)
- `per_share_cents` INTEGER (not null)
- `minimum_bill_cents` INTEGER (not null)
- `adopted_on` TEXT (not null)
- `note` TEXT (not null)

## reach

- `code` TEXT (key)
- `name` TEXT (not null)
- `head_mile` TEXT (not null)
- `toe_mile` TEXT (not null)
- `mean_velocity_fps` TEXT (not null)
- `loss_per_mile` TEXT (not null)

## reading

- `device_tag` TEXT (key, not null)
- `taken_at` TEXT (key, not null)
- `observer` TEXT (not null)
- `method` TEXT (not null)
- `head_feet` TEXT
- `tail_feet` TEXT
- `meter_total_af` TEXT
- `note` TEXT (not null)

indexes: `reading_by_time`

## reservoir

- `name` TEXT (key)
- `decree` TEXT (not null)
- `capacity_af` TEXT (not null)
- `dead_pool_af` TEXT (not null)
- `fill_opens_month` INTEGER (not null)
- `fill_opens_day` INTEGER (not null)
- `fill_closes_month` INTEGER (not null)
- `fill_closes_day` INTEGER (not null)

## rotation_window

- `water_year` INTEGER (not null)
- `turnout_code` TEXT (key, not null)
- `run_from` TEXT (key, not null)
- `run_to` TEXT (not null)
- `rate_cfs` TEXT (not null)

indexes: `rotation_by_year`

## schema_migration

- `version` INTEGER (key)
- `name` TEXT (not null)
- `applied_at` TEXT (not null)

## season

- `water_year` INTEGER (key)
- `opened` TEXT (not null)
- `closed` TEXT (not null)
- `declared_on` TEXT (not null)
- `note` TEXT (not null)

## seepage_run

- `ditch_code` TEXT (key, not null)
- `run_on` TEXT (key, not null)
- `from_station_feet` TEXT (key, not null)
- `to_station_feet` TEXT (not null)
- `inflow_cfs` TEXT (not null)
- `outflow_cfs` TEXT (not null)
- `turnouts_cfs` TEXT (not null)
- `flume_error_cfs` TEXT (not null)
- `note` TEXT (not null)

indexes: `seepage_by_ditch`

## storage_entry

- `reservoir_name` TEXT (key, not null)
- `water_year` INTEGER (key, not null)
- `account_number` INTEGER (key, not null)
- `shares` TEXT (not null)
- `allocated_af` TEXT (not null)
- `released_af` TEXT (not null)
- `spilled_af` TEXT (not null)
- `carried_in_af` TEXT (not null)

indexes: `storage_by_account`

## transfer_application

- `number` TEXT (key)
- `decree` TEXT (not null)
- `kind` TEXT (not null)
- `filed_on` TEXT (not null)
- `requested_af` TEXT (not null)
- `proved_af` TEXT (not null)
- `from_turnout` TEXT
- `to_turnout` TEXT
- `status` TEXT (not null)
- `note` TEXT (not null)
- `approved_af` TEXT
- `return_flow_af` TEXT

indexes: `transfer_by_decree`

## transfer_condition

- `number` TEXT (key, not null)
- `ordinal` INTEGER (key, not null)
- `condition` TEXT (not null)

## transfer_dry_up

- `number` TEXT (key, not null)
- `parcel_id` TEXT (key, not null)
- `offered` INTEGER (not null)

## turnout

- `code` TEXT (key)
- `ditch_code` TEXT (not null)
- `name` TEXT (not null)
- `station_feet` TEXT (not null)
- `capacity_cfs` TEXT (not null)
- `served_acres` TEXT (not null)

indexes: `turnout_by_ditch`

## water_order

- `order_id` INTEGER (key)
- `account_number` INTEGER (not null)
- `turnout_code` TEXT (not null)
- `requested_cfs` TEXT (not null)
- `run_from` TEXT (not null)
- `run_to` TEXT (not null)
- `placed_at` TEXT (not null)
- `status` TEXT (not null)
- `allowed_cfs` TEXT
- `note` TEXT (not null)

indexes: `water_order_by_account`, `water_order_by_status`, `water_order_by_turnout`

## water_right

- `decree` TEXT (key)
- `owner` TEXT (not null)
- `kind` TEXT (not null)
- `appropriation_date` TEXT (not null)
- `adjudication_year` INTEGER (not null)
- `sequence_number` INTEGER (not null)
- `diversion_mile` TEXT (not null)
- `rate_cfs` TEXT
- `volume_af` TEXT
- `ditch_code` TEXT
- `status` TEXT (not null)

indexes: `right_by_priority`

## well

- `well_id` TEXT (key)
- `decree` TEXT (not null)
- `distance_feet` TEXT (not null)
- `storativity` TEXT (not null)
- `transmissivity` TEXT (not null)
- `capacity_gpm` TEXT (not null)
- `annual_limit_af` TEXT

## well_pumping

- `well_id` TEXT (key, not null)
- `water_year` INTEGER (key, not null)
- `month` INTEGER (key, not null)
- `pumped_af` TEXT (not null)

indexes: `pumping_by_year`
