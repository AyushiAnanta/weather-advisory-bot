from pathlib import Path

import pytest

from app.sop_loader import all_activity_tags, load_sops, required_fields


SOPS_DIR = Path(__file__).parents[1] / "sops"
VALID_SOP = """id: sample
category: exercise
severity: low
applies_to: [cycling]
conditions:
  all:
    - source: current
      field: temperature_2m
      op: ">"
      value: 20
guidance: Example
"""


def test_valid_directory_loads_three_sops():
    assert len(load_sops(SOPS_DIR)) == 3


def test_uv_sop_has_expected_window():
    uv_sop = next(sop for sop in load_sops(SOPS_DIR) if sop.id == "uv-exercise-001")
    window = uv_sop.conditions.all[0].window
    assert (window.day, window.start_hour, window.end_hour) == ("today", 11, 16)


def test_picnic_sop_has_four_conditions_and_rubric():
    picnic_sop = next(sop for sop in load_sops(SOPS_DIR) if sop.id == "picnic-good-001")
    assert len(picnic_sop.conditions.all) == 4
    assert picnic_sop.rubric


def test_required_fields_are_locked_to_sample_sops():
    assert required_fields(load_sops(SOPS_DIR)) == {
        "current": [],
        "hourly": [
            "precipitation_probability",
            "temperature_2m",
            "uv_index",
            "wind_gusts_10m",
        ],
        "daily": [],
    }


def test_unknown_severity_names_file_and_field(tmp_path):
    path = tmp_path / "bad-severity.yaml"
    path.write_text(VALID_SOP.replace("severity: low", "severity: extreme"), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("bad-severity.yaml: severity:")


def test_empty_yaml_names_file_as_field(tmp_path):
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("empty.yaml: file:")


def test_yaml_list_top_level_names_file_as_field(tmp_path):
    (tmp_path / "list-top-level.yaml").write_text("- first\n- second\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("list-top-level.yaml: file:")


def test_unknown_weather_field_reports_file_field_and_allowed_list(tmp_path):
    path = tmp_path / "bad-weather-field.yaml"
    path.write_text(VALID_SOP.replace("temperature_2m", "made_up_field"), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    message = str(exc.value)
    assert message.startswith("bad-weather-field.yaml: field 'made_up_field':")
    assert "allowed:" in message
    assert "temperature_2m" in message
    assert "apparent_temperature" in message


def test_same_filename_error_must_match_field_path(tmp_path):
    # Matching only the filename would incorrectly accept this different error.
    path = tmp_path / "bad-severity.yaml"
    path.write_text(VALID_SOP.replace("temperature_2m", "made_up_field"), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("bad-severity.yaml: field 'made_up_field':")


def test_yml_file_is_loaded(tmp_path):
    (tmp_path / "sample.yml").write_text(VALID_SOP, encoding="utf-8")
    sops = load_sops(tmp_path)
    assert [sop.id for sop in sops] == ["sample"]


def test_start_hour_after_end_hour_names_file_and_field(tmp_path):
    content = VALID_SOP.replace(
        '      field: temperature_2m\n      op: ">"',
        '      field: temperature_2m\n      agg: max\n      window:\n        day: today\n        start_hour: 18\n        end_hour: 8\n      op: ">"',
    ).replace("source: current", "source: hourly")
    (tmp_path / "bad-window.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    message = str(exc.value)
    assert message.startswith("bad-window.yaml: conditions.all.0.hourly.window:")
    assert "window.start_hour" in message
    assert "end_hour" in message


def test_empty_applies_to_names_file_and_field(tmp_path):
    (tmp_path / "empty-applies.yaml").write_text(
        VALID_SOP.replace("applies_to: [cycling]", "applies_to: []"), encoding="utf-8"
    )
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("empty-applies.yaml: applies_to:")


def test_empty_id_names_file_and_field(tmp_path):
    (tmp_path / "empty-id.yaml").write_text(VALID_SOP.replace("id: sample", 'id: ""'), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("empty-id.yaml: id:")


def test_in_with_scalar_names_file_and_field(tmp_path):
    content = VALID_SOP.replace('op: ">"', 'op: "in"')
    (tmp_path / "bad-in.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("bad-in.yaml: conditions.all.0.current:")
    assert "value" in str(exc.value)
    assert "list" in str(exc.value)


def test_greater_than_with_list_names_file_and_field(tmp_path):
    content = VALID_SOP.replace("value: 20", "value: [20, 30]")
    (tmp_path / "bad-list-value.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("bad-list-value.yaml: conditions.all.0.current:")
    assert "must not be a list" in str(exc.value)


def test_unknown_extra_key_is_rejected(tmp_path):
    (tmp_path / "extra-key.yaml").write_text(VALID_SOP + "unexpected: true\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("extra-key.yaml: unexpected:")


def test_duplicate_id_raises(tmp_path):
    (tmp_path / "first.yaml").write_text(VALID_SOP, encoding="utf-8")
    (tmp_path / "second.yaml").write_text(VALID_SOP, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("second.yaml: id:")
    assert "duplicate SOP id" in str(exc.value)


def test_sop_without_conditions_raises(tmp_path):
    content = VALID_SOP.replace(
        "conditions:\n  all:\n    - source: current\n      field: temperature_2m\n      op: \">\"\n      value: 20\n",
        "conditions: {}\n",
    )
    (tmp_path / "no-conditions.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sops(tmp_path)
    assert str(exc.value).startswith("no-conditions.yaml: conditions:")


def test_all_activity_tags():
    assert all_activity_tags(load_sops(SOPS_DIR)) == [
        "cycling",
        "outdoor_exercise",
        "picnic",
    ]
