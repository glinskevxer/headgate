from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from headgate.errors import PolicyError, ValidationError
from headgate.ids import DeviceTag
from headgate.measure.telemetry import Sample, SampleRun, is_spike, rate_of_change
from headgate.model.reading import ReadingMethod

WEIR = DeviceTag("WEIR-L2-14")
START = datetime(2025, 7, 1, 6)


def sample(minutes: int, head: str, battery: str | None = "12.4") -> Sample:
    return Sample(
        device=WEIR,
        taken_at=START + timedelta(minutes=minutes),
        head_feet=Decimal(head),
        battery_volts=Decimal(battery) if battery is not None else None,
    )


def run(*samples: Sample) -> SampleRun:
    return SampleRun(device=WEIR, samples=samples)


def steady(count: int = 8, head: str = "0.60") -> SampleRun:
    return run(*(sample(index * 15, head) for index in range(count)))


def test_a_negative_reading_is_refused() -> None:
    with pytest.raises(ValidationError, match="reported -0.1 feet"):
        sample(0, "-0.1")


def test_a_negative_battery_is_refused() -> None:
    with pytest.raises(ValidationError, match="negative battery"):
        sample(0, "0.6", battery="-1")


def test_a_low_battery_is_flagged() -> None:
    assert sample(0, "0.6", battery="11.0").battery_is_low
    assert not sample(0, "0.6").battery_is_low


def test_the_rate_of_change_is_feet_an_hour() -> None:
    assert rate_of_change(sample(0, "0.60"), sample(60, "1.10")) == Decimal("0.500")


def test_two_samples_at_one_moment_are_refused() -> None:
    with pytest.raises(PolicyError, match="out of order"):
        rate_of_change(sample(0, "0.60"), sample(0, "0.70"))


def test_a_jump_beyond_what_a_ditch_does_is_a_spike() -> None:
    assert is_spike(sample(0, "0.60"), sample(10, "2.60"))
    assert not is_spike(sample(0, "0.60"), sample(60, "0.90"))


def test_a_rise_limit_of_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="rejects every sample"):
        is_spike(sample(0, "0.60"), sample(60, "0.90"), limit=Decimal("0"))


def test_a_run_holds_one_device_in_time_order() -> None:
    with pytest.raises(ValidationError, match="turned up in the run"):
        SampleRun(device=DeviceTag("WEIR-L2-20"), samples=(sample(0, "0.6"),))
    with pytest.raises(ValidationError, match="out of time order"):
        run(sample(30, "0.6"), sample(0, "0.6"))
    with pytest.raises(ValidationError, match="repeats a moment"):
        run(sample(0, "0.6"), sample(0, "0.7"))


def test_the_spikes_in_a_run_are_found() -> None:
    noisy = run(sample(0, "0.60"), sample(10, "2.60"), sample(20, "0.61"))
    assert len(noisy.spikes()) == 2
    assert len(noisy.clean().samples) == 1


def test_a_clean_run_has_no_spikes() -> None:
    assert steady().spikes() == ()
    assert steady().clean().samples == steady().samples


def test_a_stuck_sensor_is_flatlined() -> None:
    stuck = run(*(sample(index * 60, "0.60") for index in range(60)))
    assert stuck.is_flatlined()


def test_a_sensor_that_moves_is_not_flatlined() -> None:
    moving = run(*(sample(index * 60, f"0.{60 + index}") for index in range(60)))
    assert not moving.is_flatlined()


def test_a_short_run_is_never_flatlined() -> None:
    assert not run(sample(0, "0.60")).is_flatlined()
    assert not run().is_flatlined()


def test_a_flatline_window_of_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="catches every sensor"):
        steady().is_flatlined(hours=Decimal("0"))


def test_the_low_battery_samples_are_listed() -> None:
    failing = run(sample(0, "0.60"), sample(15, "0.60", battery="11.0"))
    assert len(failing.low_battery()) == 1


def test_a_run_is_thinned_to_the_interval_the_book_keeps() -> None:
    dense = run(*(sample(index * 15, "0.60") for index in range(48)))
    assert len(dense.thinned(Decimal("6"))) == 2
    assert len(dense.thinned(Decimal("1"))) == 12


def test_thinning_to_no_interval_is_refused() -> None:
    with pytest.raises(ValidationError, match="keeps every sample"):
        steady().thinned(every_hours=Decimal("0"))


def test_an_empty_run_thins_to_nothing() -> None:
    assert run().thinned() == ()
    assert run().is_empty


def test_the_readings_that_go_in_the_book_are_marked_as_a_recorder() -> None:
    dense = run(*(sample(index * 15, "0.60") for index in range(48)))
    readings = dense.readings()
    assert readings[0].method is ReadingMethod.RECORDER
    assert readings[0].observer == "telemetry"
    assert len(readings) == len(dense.thinned())


def test_a_spike_never_reaches_the_book() -> None:
    noisy = run(sample(0, "0.60"), sample(10, "2.60"), sample(400, "0.61"))
    heads = [item.head_feet for item in noisy.readings()]
    assert Decimal("2.60") not in heads
