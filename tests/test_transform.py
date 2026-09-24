import pytest

from polar_hr_calcs.transform import add_percent_of_max_hr


def test_adds_percent_column_and_converts_br_line_breaks():
    samples = "Timestamp,Heart Rate<br>16:31:50,106<br/>16:31:51,0<br>16:31:53,198"
    assert add_percent_of_max_hr(samples, "198") == (
        "Timestamp,Heart Rate,% of Max HR\n16:31:50,106,53.54\n16:31:51,0,0\n16:31:53,198,100"
    )


def test_blank_heart_rate_gets_blank_percent():
    assert add_percent_of_max_hr("Timestamp,Heart Rate<br>1,", 198) == "Timestamp,Heart Rate,% of Max HR\n1,,"


def test_replaces_existing_percent_column():
    samples = "Timestamp,Heart Rate,% of Max HR<br>1,150,1"
    assert add_percent_of_max_hr(samples, 197.0) == "Timestamp,Heart Rate,% of Max HR\n1,150,76.14"


@pytest.mark.parametrize(
    ("samples", "max_hr"),
    [
        ("", 198),  # blank samples
        (None, 198),  # missing samples
        ("Timestamp,Heart Rate<br>1,100", None),  # missing max HR
        ("Timestamp,Heart Rate<br>1,100", "0"),  # zero max HR
        ("Timestamp,Heart Rate<br>1,100", "abc"),  # non-numeric max HR
        ("Timestamp,Foo<br>1,2", 198),  # no Heart Rate column
    ],
)
def test_untransformable_sessions_return_none(samples, max_hr):
    assert add_percent_of_max_hr(samples, max_hr) is None
