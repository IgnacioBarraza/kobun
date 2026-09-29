"""
Switching a label between the roles the stylesheet knows about.

Qt does not re-evaluate a widget's style when its objectName changes, so every
place that recolours a label has to unpolish and polish it by hand. That
incantation was written out three times —the status bar, the selection hint, the
result card— which is three chances to forget the second half and wonder why the
colour did not change.
"""
from PySide6.QtWidgets import QWidget

DEFAULT = ""
SECONDARY = "SecondaryText"
ERROR = "ErrorText"
SUCCESS = "SuccessText"


def apply_text_role(widget: QWidget, role: str) -> None:
    """
    :param role: One of the objectNames StyleGenerator defines, or DEFAULT for
        the plain body colour.
    """
    widget.setObjectName(role)

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
