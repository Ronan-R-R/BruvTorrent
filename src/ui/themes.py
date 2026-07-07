"""Application themes via Qt stylesheets."""

PALETTES = {
    'dark': {
        'bg': '#1e2127', 'surface': '#252a33', 'surface_alt': '#2b313b',
        'border': '#3a414d', 'text': '#e6e9ef', 'text_dim': '#9aa3b2',
        'accent': '#4c8bf5', 'accent_text': '#ffffff', 'progress': '#3fb950',
        'selection': '#33405a',
    },
    'light': {
        'bg': '#f5f6f8', 'surface': '#ffffff', 'surface_alt': '#eef0f3',
        'border': '#d4d8de', 'text': '#1a1d23', 'text_dim': '#6b7280',
        'accent': '#2563eb', 'accent_text': '#ffffff', 'progress': '#16a34a',
        'selection': '#dbe6ff',
    },
}

_TEMPLATE = """
QMainWindow, QDialog {{ background: {bg}; }}
QWidget {{ color: {text}; font-size: 13px; }}

QToolBar {{
    background: {surface}; border: none; border-bottom: 1px solid {border};
    padding: 4px; spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent; padding: 6px 12px; border-radius: 6px; color: {text};
}}
QToolBar QToolButton:hover {{ background: {surface_alt}; }}
QToolBar QToolButton:pressed {{ background: {selection}; }}
QToolBar QToolButton:disabled {{ color: {text_dim}; }}

QMenuBar {{ background: {surface}; color: {text}; border-bottom: 1px solid {border}; }}
QMenuBar::item:selected {{ background: {surface_alt}; }}
QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent}; color: {accent_text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QTreeWidget, QTreeView, QTableWidget {{
    background: {surface}; alternate-background-color: {surface_alt};
    border: 1px solid {border}; border-radius: 8px; outline: none;
    selection-background-color: {selection};
}}
QTreeWidget::item, QTableWidget::item {{ padding: 4px; height: 22px; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {selection}; color: {text};
}}
QHeaderView::section {{
    background: {surface_alt}; color: {text_dim}; padding: 6px 8px;
    border: none; border-right: 1px solid {border}; border-bottom: 1px solid {border};
}}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {text_dim}; padding: 8px 16px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}

QProgressBar {{
    background: {surface_alt}; border: 1px solid {border}; border-radius: 6px;
    text-align: center; color: {text}; height: 18px;
}}
QProgressBar::chunk {{ background: {progress}; border-radius: 5px; }}

QPushButton {{
    background: {surface_alt}; color: {text}; border: 1px solid {border};
    border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {selection}; }}
QPushButton:default {{ background: {accent}; color: {accent_text}; border: none; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {surface}; color: {text}; border: 1px solid {border};
    border-radius: 6px; padding: 6px 8px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; selection-background-color: {accent};
}}

QStatusBar {{ background: {surface}; color: {text_dim}; border-top: 1px solid {border}; }}
QLabel {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {text_dim}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {border}; }}
"""


def stylesheet_for(theme_name: str) -> str:
    palette = PALETTES.get(theme_name, PALETTES['dark'])
    return _TEMPLATE.format(**palette)


def colors_for(theme_name: str) -> dict:
    return PALETTES.get(theme_name, PALETTES['dark'])


def apply_theme(_widget, theme_name: str) -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet_for(theme_name))
