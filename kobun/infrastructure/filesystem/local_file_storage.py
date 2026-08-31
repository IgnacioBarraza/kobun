import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from kobun.application.interfaces.file_storage import FileStorage
from kobun.domain.pdf.exceptions.file_open_exception import FileOpenException
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException

# Defensive cap on the search for a free name: with 999 variants taken,
# something is wrong upstream and failing beats looping forever.
_MAX_RENAME_ATTEMPTS = 999

WINDOWS = "win32"
MACOS = "darwin"

MACOS_OPENER = "open"
LINUX_OPENER = "xdg-open"
WINDOWS_OPENER = "explorer"


class LocalFileStorage(FileStorage):
    """
    FileStorage implementation over the local filesystem.

    `platform` and `spawn` are injected for the same reason as in
    AppDirectories: they allow verifying the open command of all three
    platforms without spawning processes or depending on the system the test
    runs on.
    """

    def __init__(
        self,
        platform: Optional[str] = None,
        spawn: Optional[Callable[[Sequence[str]], None]] = None,
    ):
        self._platform = platform if platform is not None else sys.platform
        self._spawn = spawn if spawn is not None else self._spawn_detached

    @property
    def is_windows(self) -> bool:
        return self._platform.startswith(WINDOWS)

    @property
    def is_macos(self) -> bool:
        return self._platform == MACOS

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_directory(self, path: Path) -> bool:
        return path.is_dir()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_same_file(self, first: Path, second: Path) -> bool:
        if first.exists() and second.exists():
            return os.path.samefile(first, second)

        return self._normalize(first) == self._normalize(second)

    def ensure_writable_directory(self, directory: Path) -> None:
        if not directory.exists():
            raise InvalidOutputPathException(f"El directorio de salida no existe: {directory}")

        if not directory.is_dir():
            raise InvalidOutputPathException(f"La ruta de salida no es un directorio: {directory}")

        if not os.access(directory, os.W_OK):
            raise InvalidOutputPathException(f"No hay permiso de escritura en: {directory}")

    def unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path

        for attempt in range(1, _MAX_RENAME_ATTEMPTS + 1):
            candidate = path.with_name(f"{path.stem}_{attempt}{path.suffix}")
            if not candidate.exists():
                return candidate

        raise InvalidOutputPathException(
            f"No se encontró un nombre libre para {path.name} tras {_MAX_RENAME_ATTEMPTS} intentos."
        )

    def create_directory(self, directory: Path) -> None:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InvalidOutputPathException(
                f"No se pudo crear la carpeta '{directory}': {e}"
            ) from e

    def directory_has_files(self, directory: Path) -> bool:
        if not directory.is_dir():
            return False

        # `next` over the iterator instead of listing: a folder with thousands
        # of files is answered by looking at the first entry.
        return next(directory.iterdir(), None) is not None

    def remove_directory_if_empty(self, directory: Path) -> bool:
        if not directory.is_dir() or self.directory_has_files(directory):
            return False

        try:
            directory.rmdir()
        except OSError:
            # Not being able to clean up is not worth failing an export that
            # already did what it was asked to.
            return False

        return True

    def write_bytes(self, path: Path, data: bytes) -> None:
        try:
            path.write_bytes(data)
        except OSError as e:
            raise InvalidOutputPathException(
                f"No se pudo escribir '{path.name}': {e}"
            ) from e

    def reveal_in_file_manager(self, path: Path) -> None:
        if not path.exists():
            raise FileOpenException(f"La ruta ya no está disponible: {path}")

        try:
            self._spawn(self.reveal_command(path))
        except FileOpenException:
            raise
        except Exception as e:
            raise FileOpenException(f"No se pudo mostrar '{path.name}': {e}") from e

    def reveal_command(self, path: Path) -> List[str]:
        """
        The command that shows a path in the system's file manager.

        A **folder** is opened as itself on every platform: selecting it inside
        its parent is technically closer to "reveal", but not what someone
        clicking "open folder" wants.

        For a **file** the platforms disagree:

        - Windows and macOS can select it inside its folder.
        - On Linux there is no portable way to do that —it depends on which file
          manager is installed— so the containing folder is opened. Opening the
          right folder is worth more than opening nothing.

        Windows note: `explorer` also exits with code 1 on success, which is why
        the launch is fire-and-forget and its status is never checked.
        """
        if path.is_dir():
            return [self._reveal_opener(), str(path)]

        if self.is_windows:
            # Explorer's own syntax, kept as a single argument so Popen does not
            # split it on the comma. It needs backslashes, which is what
            # str(WindowsPath) gives: a forward-slash path is the known way to
            # make this silently open the wrong window.
            #
            # Not verified on a real Windows machine. If selecting ever misses,
            # the safe fallback is dropping "/select," and passing the parent
            # folder, which is all the button promises anyway.
            return ["explorer", f"/select,{path}"]

        if self.is_macos:
            return [MACOS_OPENER, "-R", str(path)]

        return [LINUX_OPENER, str(path.parent)]

    def _reveal_opener(self) -> str:
        """The command that opens a folder as itself, per platform."""
        if self.is_windows:
            return WINDOWS_OPENER

        return MACOS_OPENER if self.is_macos else LINUX_OPENER

    def open_in_default_app(self, path: Path) -> None:
        if not path.is_file():
            raise FileOpenException(f"El archivo ya no está disponible: {path}")

        try:
            if self.is_windows:
                self._start_file(path)
            else:
                self._spawn(self.open_command(path))
        except FileOpenException:
            raise
        except Exception as e:
            raise FileOpenException(f"No se pudo abrir '{path.name}': {e}") from e

    def open_command(self, path: Path) -> List[str]:
        """
        The command that launches the default viewer on Unix-like systems.

        Windows uses the system API rather than a command, so this method is
        not called there.
        """
        opener = MACOS_OPENER if self.is_macos else LINUX_OPENER

        return [opener, str(path)]

    @staticmethod
    def _start_file(path: Path) -> None:
        """
        `os.startfile` only exists on Windows, hence the runtime lookup.
        """
        starter = getattr(os, "startfile", None)
        if starter is None:
            raise FileOpenException("Esta plataforma no expone os.startfile.")

        starter(str(path))

    @staticmethod
    def _spawn_detached(command: Sequence[str]) -> None:
        """
        Launches the viewer without waiting for it: the app must not sit
        blocked while the user reads the PDF.

        It only catches immediate failures, such as `xdg-open` not being
        installed. If the launcher starts but then finds no associated viewer,
        that happens in another process and is no longer observable from here.
        """
        subprocess.Popen(
            list(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _normalize(path: Path) -> Path:
        """
        Resolves the path without requiring it to exist, so relative paths
        ("./book.pdf") can be compared against absolute ones.
        """
        return Path(os.path.abspath(os.path.normpath(str(path))))
