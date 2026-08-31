import pytest

from kobun.domain.history.value_objects.export_kind import ExportKind


def test_kinds_round_trip_through_their_string_value():
    """This is how they come back from the JSON history."""
    assert ExportKind("split") is ExportKind.SPLIT
    assert ExportKind("images") is ExportKind.IMAGES
    assert ExportKind("pages") is ExportKind.PAGES


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        ExportKind("tablas")


def test_only_a_split_outputs_a_single_file():
    assert ExportKind.SPLIT.outputs_directory is False
    assert ExportKind.IMAGES.outputs_directory is True
    assert ExportKind.PAGES.outputs_directory is True
