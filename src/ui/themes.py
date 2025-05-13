from PySide6.QtGui import QColor, QPalette

THEMES = {
    "dark": {
        "window": "#2d2d2d",
        "window_text": "#ffffff",
        "base": "#3a3a3a",
        "alternate_base": "#2d2d2d",
        "text": "#ffffff",
        "button": "#3a3a3a",
        "button_text": "#ffffff",
        "bright_text": "#ff0000",
        "highlight": "#0066cc",
        "highlighted_text": "#ffffff",
        "link": "#5dadec",
        "tooltip_base": "#ffffdc",
        "tooltip_text": "#000000"
    },
    "light": {
        "window": "#f0f0f0",
        "window_text": "#000000",
        "base": "#ffffff",
        "alternate_base": "#f0f0f0",
        "text": "#000000",
        "button": "#f0f0f0",
        "button_text": "#000000",
        "bright_text": "#ff0000",
        "highlight": "#0066cc",
        "highlighted_text": "#ffffff",
        "link": "#5dadec",
        "tooltip_base": "#ffffdc",
        "tooltip_text": "#000000"
    },
    "blue": {
        "window": "#1e3a8a",
        "window_text": "#ffffff",
        "base": "#3b82f6",
        "alternate_base": "#1e3a8a",
        "text": "#ffffff",
        "button": "#1e40af",
        "button_text": "#ffffff",
        "bright_text": "#ff0000",
        "highlight": "#1d4ed8",
        "highlighted_text": "#ffffff",
        "link": "#93c5fd",
        "tooltip_base": "#ffffdc",
        "tooltip_text": "#000000"
    }
}

def apply_theme(app, theme_name: str):
    if theme_name not in THEMES:
        theme_name = "dark"

    theme = THEMES[theme_name]
    palette = QPalette()

    palette.setColor(QPalette.Window, QColor(theme["window"]))
    palette.setColor(QPalette.WindowText, QColor(theme["window_text"]))
    palette.setColor(QPalette.Base, QColor(theme["base"]))
    palette.setColor(QPalette.AlternateBase, QColor(theme["alternate_base"]))
    palette.setColor(QPalette.Text, QColor(theme["text"]))
    palette.setColor(QPalette.Button, QColor(theme["button"]))
    palette.setColor(QPalette.ButtonText, QColor(theme["button_text"]))
    palette.setColor(QPalette.BrightText, QColor(theme["bright_text"]))
    palette.setColor(QPalette.Highlight, QColor(theme["highlight"]))
    palette.setColor(QPalette.HighlightedText, QColor(theme["highlighted_text"]))
    palette.setColor(QPalette.Link, QColor(theme["link"]))
    palette.setColor(QPalette.ToolTipBase, QColor(theme["tooltip_base"]))
    palette.setColor(QPalette.ToolTipText, QColor(theme["tooltip_text"]))

    app.setPalette(palette)