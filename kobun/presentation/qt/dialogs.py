from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from kobun.presentation import error_messages

CONFIRM_TITLE = "Confirmar"


ATTENTION_TIMEOUT_MS = 3000
"""How long the taskbar keeps asking for attention. Long enough to be noticed
on coming back to the desk, short enough not to be still blinking minutes
later."""


def request_attention(window: QWidget) -> None:
    """
    Asks the window manager to flag the window: a flashing taskbar entry on
    Windows and most Linux desktops, a bouncing dock icon on macOS.

    Only when the window is **not** the active one. Splitting is repetitive, and
    the point of the notice is the case where the export outlived the user's
    attention: if they are looking at the window, the result card already told
    them, and flashing on top of that is noise.

    Deliberately not a modal. A dialog per export is a dialog people learn to
    dismiss without reading, and Kobun reserves those for what cannot be
    undone.
    """
    if window.isActiveWindow():
        return

    application = QApplication.instance()
    if application is None:
        return

    application.alert(window, ATTENTION_TIMEOUT_MS)


def show_error(parent: QWidget, error: Exception) -> None:
    """
    Shows an error in a modal dialog.

    Used for what interrupts the user —a failed load or export— and not for
    secondary notices: those still go to the status bar, which does not demand
    a click to keep working.
    """
    prompt = error_messages.build_error_prompt(error)

    box = QMessageBox(parent)
    box.setWindowTitle(prompt.title)
    box.setText(prompt.message)
    box.setIcon(
        QMessageBox.Icon.Critical if prompt.is_critical else QMessageBox.Icon.Warning
    )
    box.setStandardButtons(QMessageBox.StandardButton.Ok)

    if prompt.detail:
        # Folded by default: the user can copy it for a report without having
        # to read it to understand what happened.
        box.setDetailedText(prompt.detail)

    box.exec()


def ask_confirmation(parent: QWidget, question: str, accept_text: str = "Continuar") -> bool:
    """
    Asks for confirmation before an action with no way back.

    :return: True if the user accepted.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(CONFIRM_TITLE)
    box.setText(question)
    box.setIcon(QMessageBox.Icon.Question)

    accept = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(accept)

    box.exec()

    return box.clickedButton() is accept
