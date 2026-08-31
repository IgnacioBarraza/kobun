import os

import pytest

from kobun.domain.pdf.exceptions.file_open_exception import FileOpenException
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage


@pytest.fixture
def storage():
    return LocalFileStorage()


def test_exists_and_type_predicates(storage, tmp_path):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")

    assert storage.exists(file)
    assert storage.is_file(file)
    assert not storage.is_directory(file)

    assert storage.is_directory(tmp_path)
    assert not storage.is_file(tmp_path)
    assert not storage.exists(tmp_path / "fantasma.pdf")


def test_is_same_file_for_existing_paths(storage, tmp_path):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")

    assert storage.is_same_file(file, tmp_path / "sub" / ".." / "a.pdf")
    assert not storage.is_same_file(file, tmp_path / "b.pdf")


def test_is_same_file_for_paths_that_do_not_exist(storage, tmp_path):
    assert storage.is_same_file(tmp_path / "x.pdf", tmp_path / "./x.pdf")
    assert not storage.is_same_file(tmp_path / "x.pdf", tmp_path / "y.pdf")


def test_is_same_file_follows_symlinks(storage, tmp_path):
    original = tmp_path / "real.pdf"
    original.write_bytes(b"x")
    link = tmp_path / "link.pdf"
    link.symlink_to(original)

    assert storage.is_same_file(original, link)


def test_ensure_writable_directory_accepts_a_normal_directory(storage, tmp_path):
    storage.ensure_writable_directory(tmp_path)


def test_ensure_writable_directory_rejects_missing_and_non_directory(storage, tmp_path):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")

    with pytest.raises(InvalidOutputPathException, match="no existe"):
        storage.ensure_writable_directory(tmp_path / "fantasma")

    with pytest.raises(InvalidOutputPathException, match="no es un directorio"):
        storage.ensure_writable_directory(file)


def test_unique_path_returns_the_same_path_when_free(storage, tmp_path):
    libre = tmp_path / "out.pdf"

    assert storage.unique_path(libre) == libre


def test_unique_path_skips_taken_names(storage, tmp_path):
    (tmp_path / "out.pdf").write_bytes(b"x")
    assert storage.unique_path(tmp_path / "out.pdf") == tmp_path / "out_1.pdf"

    (tmp_path / "out_1.pdf").write_bytes(b"x")
    assert storage.unique_path(tmp_path / "out.pdf") == tmp_path / "out_2.pdf"


def test_unique_path_preserves_suffix_and_parent(storage, tmp_path):
    sub = tmp_path / "exports"
    sub.mkdir()
    (sub / "book_1-5.pdf").write_bytes(b"x")

    result = storage.unique_path(sub / "book_1-5.pdf")

    assert result.parent == sub
    assert result.name == "book_1-5_1.pdf"


# =========================
# Apertura con la app del sistema
# =========================

class SpawnRecorder:
    """Reemplaza el lanzamiento real de procesos y registra el comando."""

    def __init__(self, error: Exception = None):
        self.commands = []
        self._error = error

    def __call__(self, command):
        self.commands.append(list(command))
        if self._error is not None:
            raise self._error


@pytest.fixture
def file(tmp_path):
    path = tmp_path / "export.pdf"
    path.write_bytes(b"%PDF")
    return path


def test_linux_uses_xdg_open(file):
    recorder = SpawnRecorder()

    LocalFileStorage(platform="linux", spawn=recorder).open_in_default_app(file)

    assert recorder.commands == [["xdg-open", str(file)]]


def test_macos_uses_open(file):
    recorder = SpawnRecorder()

    LocalFileStorage(platform="darwin", spawn=recorder).open_in_default_app(file)

    assert recorder.commands == [["open", str(file)]]


def test_windows_uses_the_system_api_not_a_command(file, monkeypatch):
    llamadas = []
    monkeypatch.setattr(os, "startfile", llamadas.append, raising=False)
    recorder = SpawnRecorder()

    LocalFileStorage(platform="win32", spawn=recorder).open_in_default_app(file)

    assert llamadas == [str(file)]
    assert recorder.commands == [], "Windows no debe pasar por subprocess"


def test_missing_file_is_reported_before_launching_anything(tmp_path):
    recorder = SpawnRecorder()
    storage = LocalFileStorage(platform="linux", spawn=recorder)

    with pytest.raises(FileOpenException, match="ya no está disponible"):
        storage.open_in_default_app(tmp_path / "borrado.pdf")

    assert recorder.commands == []


def test_a_directory_cannot_be_opened_as_a_file(tmp_path):
    folder = tmp_path / "carpeta.pdf"
    folder.mkdir()

    with pytest.raises(FileOpenException, match="ya no está disponible"):
        LocalFileStorage(platform="linux", spawn=SpawnRecorder()).open_in_default_app(folder)


def test_a_missing_opener_becomes_a_domain_exception(file):
    """A system without xdg-open installed must not blow up with FileNotFoundError."""
    recorder = SpawnRecorder(error=FileNotFoundError("xdg-open"))
    storage = LocalFileStorage(platform="linux", spawn=recorder)

    with pytest.raises(FileOpenException, match="No se pudo abrir 'export.pdf'"):
        storage.open_in_default_app(file)


def test_the_original_error_is_preserved_as_cause(file):
    original = OSError("permiso denegado")
    storage = LocalFileStorage(platform="linux", spawn=SpawnRecorder(error=original))

    with pytest.raises(FileOpenException) as error:
        storage.open_in_default_app(file)

    assert error.value.__cause__ is original


def test_open_command_is_inspectable_without_launching(file):
    assert LocalFileStorage(platform="linux").open_command(file) == ["xdg-open", str(file)]
    assert LocalFileStorage(platform="darwin").open_command(file) == ["open", str(file)]


def test_default_construction_still_works():
    """The rest of the code builds LocalFileStorage() with no arguments."""
    storage = LocalFileStorage()

    assert isinstance(storage.is_windows, bool)
# =========================
# Carpetas
# =========================

def test_create_directory_makes_missing_parents(storage, tmp_path):
    target = tmp_path / "a" / "b" / "c"

    storage.create_directory(target)

    assert target.is_dir()


def test_create_directory_is_idempotent(storage, tmp_path):
    target = tmp_path / "existente"
    target.mkdir()

    storage.create_directory(target)

    assert target.is_dir()


def test_create_directory_over_a_file_is_a_domain_exception(storage, tmp_path):
    taken = tmp_path / "archivo"
    taken.write_bytes(b"x")

    with pytest.raises(InvalidOutputPathException, match="No se pudo crear la carpeta"):
        storage.create_directory(taken)


def test_directory_has_files_reports_content(storage, tmp_path):
    empty = tmp_path / "vacia"
    empty.mkdir()
    occupied = tmp_path / "ocupada"
    occupied.mkdir()
    (occupied / "x.png").write_bytes(b"x")

    assert storage.directory_has_files(empty) is False
    assert storage.directory_has_files(occupied) is True


def test_directory_has_files_counts_subfolders_too(storage, tmp_path):
    parent = tmp_path / "padre"
    (parent / "hija").mkdir(parents=True)

    assert storage.directory_has_files(parent) is True


def test_directory_has_files_is_false_for_what_is_not_a_directory(storage, tmp_path):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")

    assert storage.directory_has_files(file) is False
    assert storage.directory_has_files(tmp_path / "fantasma") is False


def test_remove_directory_if_empty_deletes_only_empty_ones(storage, tmp_path):
    empty = tmp_path / "vacia"
    empty.mkdir()

    assert storage.remove_directory_if_empty(empty) is True
    assert not empty.exists()


def test_remove_directory_if_empty_leaves_content_alone(storage, tmp_path):
    """It cleans up after Kobun; it does not delete the user's files."""
    occupied = tmp_path / "ocupada"
    occupied.mkdir()
    (occupied / "ajeno.txt").write_bytes(b"no me toques")

    assert storage.remove_directory_if_empty(occupied) is False
    assert (occupied / "ajeno.txt").read_bytes() == b"no me toques"


def test_remove_directory_if_empty_is_safe_on_a_file_or_a_ghost(storage, tmp_path):
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")

    assert storage.remove_directory_if_empty(file) is False
    assert storage.remove_directory_if_empty(tmp_path / "fantasma") is False
    assert file.exists()


# =========================
# Escritura
# =========================

def test_write_bytes_creates_the_file(storage, tmp_path):
    target = tmp_path / "imagen.png"

    storage.write_bytes(target, b"\x89PNG datos")

    assert target.read_bytes() == b"\x89PNG datos"


def test_write_bytes_replaces_an_existing_file(storage, tmp_path):
    target = tmp_path / "imagen.png"
    target.write_bytes(b"anterior")

    storage.write_bytes(target, b"nueva")

    assert target.read_bytes() == b"nueva"


def test_write_bytes_into_a_missing_folder_is_a_domain_exception(storage, tmp_path):
    with pytest.raises(InvalidOutputPathException, match="No se pudo escribir"):
        storage.write_bytes(tmp_path / "fantasma" / "imagen.png", b"x")


# =========================
# Mostrar en el explorador
# =========================

def test_windows_selects_the_file_inside_its_folder(file):
    recorder = SpawnRecorder()

    LocalFileStorage(platform="win32", spawn=recorder).reveal_in_file_manager(file)

    assert recorder.commands == [["explorer", f"/select,{file}"]]


def test_macos_selects_the_file_inside_its_folder(file):
    recorder = SpawnRecorder()

    LocalFileStorage(platform="darwin", spawn=recorder).reveal_in_file_manager(file)

    assert recorder.commands == [["open", "-R", str(file)]]


def test_linux_opens_the_containing_folder(file):
    """
    There is no portable way to select a file on Linux —it depends on the file
    manager— so opening the right folder is what is offered.
    """
    recorder = SpawnRecorder()

    LocalFileStorage(platform="linux", spawn=recorder).reveal_in_file_manager(file)

    assert recorder.commands == [["xdg-open", str(file.parent)]]


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_a_folder_is_opened_as_itself_everywhere(tmp_path, platform):
    """Someone clicking "open folder" wants it open, not selected in its parent."""
    folder = tmp_path / "libro_imagenes_1-5"
    folder.mkdir()
    recorder = SpawnRecorder()

    LocalFileStorage(platform=platform, spawn=recorder).reveal_in_file_manager(folder)

    assert str(folder) in recorder.commands[0]
    assert not any("/select" in part for part in recorder.commands[0])


def test_revealing_a_missing_path_is_reported_before_launching_anything(tmp_path):
    recorder = SpawnRecorder()
    storage = LocalFileStorage(platform="linux", spawn=recorder)

    with pytest.raises(FileOpenException, match="ya no está disponible"):
        storage.reveal_in_file_manager(tmp_path / "borrado.pdf")

    assert recorder.commands == []


def test_a_missing_file_manager_becomes_a_domain_exception(file):
    recorder = SpawnRecorder(error=FileNotFoundError("xdg-open"))
    storage = LocalFileStorage(platform="linux", spawn=recorder)

    with pytest.raises(FileOpenException, match="No se pudo mostrar 'export.pdf'"):
        storage.reveal_in_file_manager(file)


def test_reveal_command_is_inspectable_without_launching(file):
    assert LocalFileStorage(platform="linux").reveal_command(file) == [
        "xdg-open", str(file.parent)
    ]
    assert LocalFileStorage(platform="darwin").reveal_command(file) == [
        "open", "-R", str(file)
    ]
    assert LocalFileStorage(platform="win32").reveal_command(file) == [
        "explorer", f"/select,{file}"
    ]
