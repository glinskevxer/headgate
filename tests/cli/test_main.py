from pathlib import Path

from click.testing import CliRunner

from headgate import __version__
from headgate.cli.main import main


def run(arguments: list[str], book: Path) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["--book", str(book), *arguments])
    return result.exit_code, result.output


def test_the_version_is_the_package_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_a_new_book_is_set_up_and_reports_its_district(tmp_path: Path) -> None:
    book = tmp_path / "district.sqlite3"
    code, output = run(
        ["init", "--name", "Sanpete Ditch Company", "--state", "ut", "--stream", "Sanpete Creek"],
        book,
    )
    assert code == 0
    assert "Sanpete Ditch Company set up" in output
    assert book.exists()


def test_setting_up_the_same_book_twice_is_refused(tmp_path: Path) -> None:
    book = tmp_path / "district.sqlite3"
    run(["init", "--name", "Sanpete", "--state", "ut", "--stream", "Creek"], book)
    code, output = run(["init", "--name", "Other", "--state", "ut", "--stream", "Creek"], book)
    assert code != 0
    assert "already holds Sanpete" in output


def test_status_on_a_book_that_was_never_set_up(tmp_path: Path) -> None:
    code, output = run(["status"], tmp_path / "empty.sqlite3")
    assert code == 0
    assert "never been set up" in output


def test_status_reports_the_district_and_the_schema(tmp_path: Path) -> None:
    book = tmp_path / "district.sqlite3"
    run(["init", "--name", "Sanpete", "--state", "ut", "--stream", "Sanpete Creek"], book)
    code, output = run(["status"], book)
    assert code == 0
    assert "district: Sanpete" in output
    assert "at version" in output
    assert "pending:  0" in output


def test_migrating_a_book_that_is_current_says_so(tmp_path: Path) -> None:
    book = tmp_path / "district.sqlite3"
    run(["init", "--name", "Sanpete", "--state", "ut", "--stream", "Creek"], book)
    code, output = run(["migrate-book"], book)
    assert code == 0
    assert "already at version" in output


def test_migrating_an_empty_book_applies_everything(tmp_path: Path) -> None:
    code, output = run(["migrate-book"], tmp_path / "fresh.sqlite3")
    assert code == 0
    assert "applied" in output


def test_the_miners_inch_standard_is_checked(tmp_path: Path) -> None:
    code, output = run(
        [
            "init",
            "--name",
            "Sanpete",
            "--state",
            "ut",
            "--stream",
            "Creek",
            "--miners-inch",
            "atlantis",
        ],
        tmp_path / "district.sqlite3",
    )
    assert code != 0
    assert "atlantis" in output


def test_the_book_can_come_from_the_environment(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    book = tmp_path / "from-env.sqlite3"
    monkeypatch.setenv("HEADGATE_BOOK", str(book))
    result = CliRunner().invoke(
        main, ["init", "--name", "Sanpete", "--state", "ut", "--stream", "Creek"]
    )
    assert result.exit_code == 0
    assert book.exists()


def test_the_group_prints_help_without_touching_a_book(tmp_path: Path) -> None:
    code, output = run(["--help"], tmp_path / "nothing.sqlite3")
    assert code == 0
    assert "Water accounting for a ditch company" in output
    assert not (tmp_path / "nothing.sqlite3").exists()
