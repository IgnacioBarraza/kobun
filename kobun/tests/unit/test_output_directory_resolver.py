import pytest

from kobun.application.services.output_directory_resolver import OutputDirectoryResolver
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage


@pytest.fixture
def resolver():
    return OutputDirectoryResolver(LocalFileStorage())


def test_a_folder_that_does_not_exist_is_created(resolver, tmp_path):
    target = tmp_path / "libro_figuras"

    assert resolver.resolve(target) == target
    assert target.is_dir()


def test_missing_parents_are_created_too(resolver, tmp_path):
    target = tmp_path / "exports" / "2026" / "libro_figuras"

    resolver.resolve(target)

    assert target.is_dir()


def test_an_existing_empty_folder_is_used_as_is(resolver, tmp_path):
    target = tmp_path / "vacia"
    target.mkdir()

    assert resolver.resolve(target) == target


def test_a_folder_that_already_holds_files_is_accepted(resolver, tmp_path):
    """
    The whole point of the redesign: pointing two extractions at one folder is
    the normal case, not a conflict. Treating a non-empty folder as occupied made
    the destination single-use and forced a folder per run.
    """
    target = tmp_path / "mis figuras"
    target.mkdir()
    (target / "libro_p003_img01.png").write_bytes(b"anterior")

    assert resolver.resolve(target) == target


def test_nothing_in_the_folder_is_touched(resolver, tmp_path):
    target = tmp_path / "mis figuras"
    target.mkdir()
    previous = target / "ajeno.txt"
    previous.write_bytes(b"no me toques")

    resolver.resolve(target)

    assert previous.read_bytes() == b"no me toques"
    assert sorted(p.name for p in target.iterdir()) == ["ajeno.txt"]


def test_a_file_sitting_at_the_destination_path_is_rejected(resolver, tmp_path):
    taken = tmp_path / "libro_figuras"
    taken.write_bytes(b"soy un archivo")

    with pytest.raises(InvalidOutputPathException, match="no puede usarse como carpeta"):
        resolver.resolve(taken)


def test_a_folder_that_cannot_be_created_is_reported(resolver, tmp_path):
    blocker = tmp_path / "bloqueado"
    blocker.write_bytes(b"soy un archivo")

    with pytest.raises(InvalidOutputPathException):
        resolver.resolve(blocker / "dentro")
