from conftest import filing, write_dataset

from insider_radar import ingest


def test_dates_are_stored_in_iso_format(load):
    conn = load([filing("2024-03-05", owner=11)])
    assert conn.execute("SELECT filing_date FROM submissions").fetchone()[0] == "2024-03-05"
    assert conn.execute("SELECT trans_date FROM trans").fetchone()[0] == "2024-03-05"


def test_leading_zeros_are_stripped_from_ciks(load):
    conn = load([filing("2024-03-05", owner=11, issuer=1000)])
    assert conn.execute("SELECT issuer_cik FROM submissions").fetchone()[0] == "1000"
    assert conn.execute("SELECT owner_cik FROM owners").fetchone()[0] == "11"


def test_numbers_are_numeric(load):
    conn = load([filing("2024-03-05", owner=11, shares=250, price=12.5)])
    assert conn.execute("SELECT shares, price FROM trans").fetchone() == (250.0, 12.5)


def test_files_nested_in_a_folder_inside_the_zip(load):
    conn = load([filing("2024-03-05", owner=11)], nested=True)
    assert conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1


def test_plan_flag_is_null_when_the_data_set_predates_it(load):
    conn = load([filing("2022-03-05", owner=11)], with_plan_flag=False)
    assert conn.execute("SELECT aff10b5one FROM submissions").fetchone()[0] is None


def test_plan_flag_is_read_when_present(load):
    conn = load([filing("2024-03-05", owner=11, plan="1"), filing("2024-03-06", owner=12, plan="0")])
    assert [r[0] for r in conn.execute("SELECT aff10b5one FROM submissions ORDER BY filing_date")] == [1, 0]


def test_loading_twice_does_not_duplicate(conn, tmp_path):
    path = write_dataset(tmp_path / "2024q1_form345.zip", [filing("2024-03-05", owner=11)])
    assert ingest.load(conn, path) == 1
    assert ingest.load(conn, path) == 1
    for table in ("submissions", "owners", "trans", "loaded_files"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_joint_filing_keeps_every_owner(load):
    conn = load([filing("2024-03-05", owner=11, extra_owners=((12, "Director"),))])
    assert conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 2
