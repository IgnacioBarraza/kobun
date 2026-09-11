from kobun.shared.config.app_settings import THEME_ICONS_DIRECTORY
from kobun.shared.theme import AppTheme

# Radii in pixels. Named rather than repeated so adjusting the roundness of the
# whole app is changing one number.
RADIUS_SMALL = 6
RADIUS_MEDIUM = 9
RADIUS_LARGE = 12
RADIUS_AREA = 14


class StyleGenerator:
    """
    Transforma un AppTheme en una cadena QSS (Qt Style Sheets).

    Every colour in the application comes from here: the widgets carry no
    styles of their own, so switching theme is replacing this sheet and nothing
    else.

    Shape too: surfaces and space are preferred over frames. Only the elements
    where a border communicates something carry one —the drop area, which
    invites dropping, and the editable fields— instead of boxing every block.
    """

    @staticmethod
    def chevron_url(theme: AppTheme) -> str:
        """
        Path to the chevron icon for the combo boxes.

        Qt does not allow drawing the arrow with styles: `QComboBox::down-arrow`
        only accepts an image. A neutral grey per light or dark variant is used,
        which works with any accent colour.

        Emitted in posix format because QSS expects forward slashes even on
        Windows.
        """
        variant = "dark" if theme.is_dark else "light"

        return (THEME_ICONS_DIRECTORY / f"chevron_{variant}.svg").as_posix()

    @staticmethod
    def generate(theme: AppTheme) -> str:
        bg = theme.get_color("background")
        surface = theme.get_color("surface")
        surface_alt = theme.get_color("surface_alt", surface)
        primary = theme.get_color("primary")
        primary_hover = theme.get_color("primary_hover", primary)
        border = theme.get_color("border")
        border_strong = theme.get_color("border_strong", border)
        danger = theme.get_color("danger", "#b3261e")
        success = theme.get_color("success", "#3f7d58")

        text_primary = theme.get_text_color("primary")
        text_secondary = theme.get_text_color("secondary")
        text_inverse = theme.get_text_color("inverse")
        text_disabled = theme.get_text_color("disabled", text_secondary)
        chevron = StyleGenerator.chevron_url(theme)

        return f"""
        QWidget {{
            background-color: {bg};
            color: {text_primary};
            font-size: 13px;
        }}

        /* Without this the QLabels paint the general background over the panel
           containing them, and a box shows around every piece of text. */
        QLabel {{
            background: transparent;
        }}

        QFrame#MainContainer {{
            background-color: {bg};
        }}

        QFrame#Sidebar {{
            background-color: {surface};
            border: none;
        }}

        QLabel#Logo {{
            font-size: 23px;
            font-weight: bold;
            color: {primary};
        }}

        QLabel#Title {{
            font-size: 20px;
            font-weight: bold;
        }}

        QLabel#SectionLabel {{
            color: {text_secondary};
            font-size: 11px;
            font-weight: bold;
        }}

        QLabel#SecondaryText {{
            color: {text_secondary};
            font-size: 11px;
        }}

        QLabel#ErrorText {{
            color: {danger};
        }}

        QLabel#SuccessText {{
            color: {success};
        }}

        /* One pixel: divides without boxing in. */
        QFrame#Hairline {{
            background-color: {border};
            border: none;
            max-height: 1px;
        }}

        /* Primary button */
        QPushButton#PrimaryButton {{
            background-color: {primary};
            color: {text_inverse};
            border: none;
            border-radius: {RADIUS_LARGE}px;
            padding: 12px 22px;
            font-weight: bold;
            font-size: 14px;
        }}

        QPushButton#PrimaryButton:hover {{
            background-color: {primary_hover};
        }}

        QPushButton#PrimaryButton:disabled {{
            background-color: {surface_alt};
            color: {text_disabled};
        }}

        /* Secondary buttons */
        QPushButton {{
            background-color: {surface};
            color: {text_primary};
            border: 1px solid {border};
            border-radius: {RADIUS_MEDIUM}px;
            padding: 9px 15px;
        }}

        QPushButton:hover {{
            border-color: {border_strong};
            background-color: {surface_alt};
        }}

        QPushButton:disabled {{
            color: {text_disabled};
            border-color: {border};
        }}

        /* Navigation: text with an accent bar, not a boxed-in button. */
        QPushButton#NavButton {{
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            border-radius: 0;
            padding: 11px 12px;
            text-align: left;
            color: {text_secondary};
        }}

        QPushButton#NavButton:hover {{
            background-color: {surface_alt};
            color: {text_primary};
        }}

        QPushButton#NavButton:checked {{
            border-left-color: {primary};
            background-color: {surface_alt};
            color: {text_primary};
            font-weight: bold;
        }}

        /* Inputs */
        QLineEdit {{
            background-color: {surface_alt};
            border: 1px solid transparent;
            border-radius: {RADIUS_MEDIUM}px;
            padding: 10px 12px;
            color: {text_primary};
            selection-background-color: {primary};
            selection-color: {text_inverse};
        }}

        QLineEdit:hover {{
            border-color: {border};
        }}

        QLineEdit:focus {{
            border-color: {primary};
            background-color: {surface};
        }}

        QLineEdit:disabled {{
            color: {text_disabled};
            background-color: {surface};
        }}

        QComboBox {{
            background-color: {surface_alt};
            border: 1px solid transparent;
            border-radius: {RADIUS_MEDIUM}px;
            padding: 9px 12px;
            /* Forces the styleable list instead of the system's native popup. */
            combobox-popup: 0;
        }}

        QComboBox:hover {{
            border-color: {border};
        }}

        QComboBox:focus, QComboBox:on {{
            border-color: {primary};
        }}

        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 30px;
            border: none;
            background: transparent;
        }}

        QComboBox::down-arrow {{
            image: url("{chevron}");
            width: 12px;
            height: 12px;
        }}

        QComboBox QAbstractItemView {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: {RADIUS_MEDIUM}px;
            padding: 5px;
            outline: none;
        }}

        /* Without ::item the rows come out cramped and with no hover highlight. */
        QComboBox QAbstractItemView::item {{
            min-height: 28px;
            padding: 5px 9px;
            border-radius: {RADIUS_SMALL}px;
            color: {text_primary};
        }}

        QComboBox QAbstractItemView::item:hover {{
            background-color: {surface_alt};
        }}

        QComboBox QAbstractItemView::item:selected {{
            background-color: {primary};
            color: {text_inverse};
        }}

        /* Drop area: here the border does communicate —it invites dropping—
           so it stays dashed, only softer and more rounded. */
        QFrame#DropArea {{
            background-color: {surface};
            border: 2px dashed {border};
            border-radius: {RADIUS_AREA}px;
        }}

        QFrame#DropArea:hover {{
            border-color: {border_strong};
        }}

        QFrame#DropArea[dragActive="true"] {{
            border-color: {primary};
            background-color: {surface_alt};
        }}

        /* History: no frame. The surface already separates it from the background. */
        QListWidget {{
            background-color: {surface};
            border: none;
            border-radius: {RADIUS_LARGE}px;
            padding: 8px;
            outline: none;
        }}

        QListWidget::item {{
            padding: 11px 12px;
            border-radius: {RADIUS_MEDIUM}px;
            color: {text_primary};
        }}

        QListWidget::item:hover {{
            background-color: {surface_alt};
        }}

        QListWidget::item:selected {{
            background-color: {primary};
            color: {text_inverse};
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 4px 2px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {border_strong};
            border-radius: 4px;
            min-height: 28px;
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        /* Indeterminate spinner */
        QProgressBar {{
            background-color: {surface_alt};
            border: none;
            border-radius: 3px;
            max-height: 5px;
        }}

        QProgressBar::chunk {{
            background-color: {primary};
            border-radius: 3px;
        }}

        /* Result card: the accent bar on the left is what makes it read as an
           outcome rather than another panel of options. A full coloured surface
           was too loud for something that appears after every export. */
        QFrame#ResultCard {{
            background-color: {surface};
            border: none;
            border-left: 3px solid {success};
            border-radius: {RADIUS_MEDIUM}px;
        }}

        QLabel#ResultTitle {{
            font-size: 14px;
            font-weight: bold;
            color: {text_primary};
        }}

        /* The resolution field. Styled to match QLineEdit: under Fusion an
           unstyled QSpinBox keeps its native arrows and is the one widget that
           gives away that this is Qt. */
        QSpinBox {{
            background-color: {surface_alt};
            border: 1px solid transparent;
            border-radius: {RADIUS_MEDIUM}px;
            padding: 9px 10px;
            min-width: 96px;
            color: {text_primary};
            selection-background-color: {primary};
            selection-color: {text_inverse};
        }}

        QSpinBox:hover {{
            border-color: {border};
        }}

        QSpinBox:focus {{
            border-color: {primary};
            background-color: {surface};
        }}

        QSpinBox:disabled {{
            color: {text_disabled};
            background-color: {surface};
        }}

        /* The stepper buttons are hidden rather than styled. QSS cannot rotate
           an image, and it does not draw CSS border-triangles either, so every
           attempt at an up arrow came out as a stray square in the corner. The
           field is typed into and responds to the wheel and the arrow keys, so
           nothing is lost but the artefact. */
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 0;
            height: 0;
            border: none;
            background: transparent;
        }}

        /* The history tooltips are long; with no style of their own they
           inherit the system's and turn illegible in a dark theme. */
        QToolTip {{
            background-color: {surface};
            color: {text_primary};
            border: 1px solid {border_strong};
            border-radius: {RADIUS_SMALL}px;
            padding: 7px 9px;
        }}
        """
