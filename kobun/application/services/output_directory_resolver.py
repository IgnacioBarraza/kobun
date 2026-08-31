from pathlib import Path

from kobun.application.interfaces.file_storage import FileStorage
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException


class OutputDirectoryResolver:
    """
    Turns whatever the user picked as a destination folder into one that exists
    and accepts writes.

    It applies **no overwrite policy**, and that is the point. It used to: a
    folder that already held files was treated as occupied, which meant a second
    extraction into the same folder was an error. That made the destination
    effectively single-use and pushed people into one folder per run — the
    opposite of picking a folder and collecting things in it.

    The policy belongs one level down, on each file, where a real collision can
    actually be identified: writing `libro_p007_img01.png` next to
    `libro_p003_img01.png` conflicts with nothing.
    """

    def __init__(self, file_storage: FileStorage):
        self._file_storage = file_storage

    def resolve(self, requested: Path) -> Path:
        """
        :param requested: Folder to write into. It does not need to exist yet;
            it is created, parents included.
        :return: A folder that exists and is writable.
        :raises InvalidOutputPathException: If the path is taken by a file, or
            the folder cannot be created or written to.
        """
        target = Path(requested)

        if self._file_storage.is_file(target):
            raise InvalidOutputPathException(
                f"Ya existe un archivo con esa ruta y no puede usarse como carpeta: {target}"
            )

        self._file_storage.create_directory(target)
        self._file_storage.ensure_writable_directory(target)

        return target
