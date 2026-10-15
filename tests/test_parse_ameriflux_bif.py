"""BIF grouping must preserve source evidence and incomplete dates."""
import csv
import json

import openpyxl
import pytest

from site_kb.scripts.parse_ameriflux_bif import REQUIRED, normalize_date, read_rows, reconstruct_records, stage_bif


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REQUIRED)
        writer.writerows(rows)


def test_groups_duplicates_and_qualifiers_preserved(tmp_path):
    path = tmp_path / "input.csv"
    write_csv(path, [
        ["US-Ne1", "1", "GRP_LAI", "LAI_TOT", " 2.1 "],
        ["US-Ne1", "1", "GRP_LAI", "LAI_TOT", "2.2"],
        ["US-Ne1", "1", "GRP_LAI", "LAI_DATE_UNC", "15"],
        ["US-Ne1", "1", "GRP_LAI", "LAI_UNIT", "m2 m-2"],
        ["US-Ne1", "1", "GRP_LAI", "LAI_COMMENT", "Verbatim, with | punctuation"],
        ["US-Ne1", "1", "GRP_DM_PLANT", "DM_PLANT_COMMENT", "undated planting"],
        ["US-Ne2", "1", "GRP_LAI", "LAI_TOT", "3"],
        ["US-Ne1", "2", "GRP_UNKNOWN", "UNKNOWN", "x"],
    ])
    rows, sheet = read_rows(path)
    records = reconstruct_records(rows)
    assert sheet is None and len(records) == 4
    lai = next(r for r in records if r["site_id"] == "US-Ne1" and r["variable_group"] == "GRP_LAI")
    assert lai["record_kind"] == "OBSERVATION" and lai["date_status"] == "UNDATED"
    assert lai["fields"]["LAI_TOT"] == [" 2.1 ", "2.2"]
    assert lai["fields"]["LAI_UNIT"] == ["m2 m-2"]
    assert lai["fields"]["LAI_COMMENT"] == ["Verbatim, with | punctuation"]
    assert len(lai["source_rows"]) == 5 and not lai["dates"]
    assert lai["review_issues"]
    assert next(r for r in records if r["variable_group"] == "GRP_DM_PLANT")["record_kind"] == "MANAGEMENT_EVENT"
    assert next(r for r in records if r["variable_group"] == "GRP_UNKNOWN")["record_kind"] == "UNCLASSIFIED"


@pytest.mark.parametrize("raw,expected", [("2020", ("2020", "year")), ("202002", ("2020-02", "month")),
    ("20200229", ("2020-02-29", "day")), ("20210229", (None, None)),
    ("202001011230", ("2020-01-01T12:30", "minute")), ("-9999", (None, None)),
    ("uncertain", (None, None))])
def test_dates_preserve_precision_and_reject_invalid_calendar_dates(raw, expected):
    assert normalize_date(raw) == expected


def test_excel_staging_archives_source_and_preserves_depth_and_intervals(tmp_path):
    path = tmp_path / "input.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AMF-BIF"
    ws.append(REQUIRED)
    for variable, value in [("SOIL_CHEM", "2.5"), ("SOIL_CHEM_DATE_START", "202001"),
                            ("SOIL_CHEM_DATE_END", "202002"), ("SOIL_CHEM_PROFILE_MIN", "-10"),
                            ("SOIL_CHEM_COMMENT", "  keep spacing  ")]:
        ws.append(["US-Ne1", "1", "GRP_SOIL_CHEM", variable, value])
    wb.save(path)
    raw, output = tmp_path / "raw", tmp_path / "staged"
    result_path = stage_bif(path, raw, output)
    result = json.loads(result_path.read_text())
    record = result["records"][0]
    assert record["record_kind"] == "OBSERVATION" and record["date_status"] == "DATED"
    assert [d["precision"] for d in record["dates"]] == ["month", "month"]
    assert record["fields"]["SOIL_CHEM_PROFILE_MIN"] == ["-10"]
    assert record["fields"]["SOIL_CHEM_COMMENT"] == ["  keep spacing  "]
    assert next(raw.glob("*.xlsx")).read_bytes() == path.read_bytes()
    assert result["sheet"] == "AMF-BIF" and "sites" not in result


def test_invalid_date_does_not_change_record_kind(tmp_path):
    path = tmp_path / "input.csv"
    write_csv(path, [["US-Ne1", "1", "GRP_LAI", "LAI_DATE", "20210229"]])
    record = reconstruct_records(read_rows(path)[0])[0]
    assert record["record_kind"] == "OBSERVATION"
    assert record["date_status"] == "UNPARSEABLE"
    assert record["dates"][0]["raw_value"] == "20210229"


def test_bad_columns_fail_before_creating_outputs(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("SITE_ID,VARIABLE\nUS-Ne1,LAI\n")
    with pytest.raises(ValueError, match="headers"):
        stage_bif(path, tmp_path / "raw", tmp_path / "staged")
    assert not (tmp_path / "raw").exists()


def test_formulas_and_implicit_sheet_fallback_are_rejected(tmp_path):
    path = tmp_path / "formula.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(REQUIRED)
    ws.append(["US-Ne1", "1", "GRP_LAI", "LAI_TOT", "=1+2"])
    wb.save(path)
    with pytest.raises(ValueError, match="Missing BIF sheet"):
        read_rows(path)
    with pytest.raises(ValueError, match="formulas"):
        read_rows(path, ws.title)
