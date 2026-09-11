from abc import ABC, abstractmethod
from pathlib import Path


class FileStorage(ABC):
    """
    Filesystem access contract, so the application and domain layers can
    reason about paths without importing `os`.

    It exists to make the output path policy testable without touching disk,
    and to allow substituting it —for a remote storage, say— without changing
    the use cases.
    """

    @abstractmethod
    def exists(self, path: Path) -> bool:
        pass

    @abstractmethod
    def is_directory(self, path: Path) -> bool:
        pass

    @abstractmethod
    def is_file(self, path: Path) -> bool:
        pass

    @abstractmethod
    def is_same_file(self, first: Path, second: Path) -> bool:
        """
        True if both paths point at the same file, resolving relative paths
        and symbolic links.
        """
        pass

    @abstractmethod
    def ensure_writable_directory(self, directory: Path) -> None:
        """
        Checks the directory exists and accepts writes.

        :raises InvalidOutputPathException: If it does not exist, is not a
            directory, or there is no write permission.
        """
        pass

    @abstractmethod
    def unique_path(self, path: Path) -> Path:
        """
        Returns the path as is if free, or the first available numbered
        variant: book.pdf -> book_1.pdf -> book_2.pdf.
        """
        pass

    @abstractmethod
    def create_directory(self, directory: Path) -> None:
        """
        Creates the directory, including any missing parent, and does nothing
        if it already exists.

        :raises InvalidOutputPathException: If it cannot be created.
        """
        pass

    @abstractmethod
    def directory_has_files(self, directory: Path) -> bool:
        """
        True if the directory exists and holds at least one entry.

        Used to decide whether writing an extraction into it would mix new
        files with someone else's, which is what the overwrite policy is asked
        about.
        """
        pass

    @abstractmethod
    def remove_directory_if_empty(self, directory: Path) -> bool:
        """
        Deletes the directory only if it holds nothing, and reports whether it
        did.

        Exists so an extraction that found nothing does not leave a folder
        behind. Probing a few pages for images is a normal thing to do, and each
        probe leaving an empty "libro_imagenes_7" next to the PDF turns the
        feature into litter.

        Never recursive, and never on a directory with content: this cleans up
        after Kobun, it does not delete the user's files.
        """
        pass

    @abstractmethod
    def write_bytes(self, path: Path, data: bytes) -> None:
        """
        Writes a file whole, replacing it if it exists.

        It exists so the extraction use case can persist images without
        importing `open`: the application layer must not touch the filesystem
        directly, and an extraction writes files that are not PDFs and
        therefore never pass through the PDF engine.

        :raises InvalidOutputPathException: If the write fails.
        """
        pass

    @abstractmethod
    def reveal_in_file_manager(self, path: Path) -> None:
        """
        Shows the file or folder in the system's file manager: selected inside
        its folder when it is a file, opened when it is a folder.

        It does not wait for the manager to finish: it only launches it.

        :raises FileOpenException: If the path does not exist or the system
            could not launch anything.
        """
        pass

    @abstractmethod
    def open_in_default_app(self, path: Path) -> None:
        """
        Opens the file with the system's default application.

        It does not wait for that application to finish: it only launches it.

        :raises FileOpenException: If the file does not exist or the system
            could not launch it.
        """
        pass
