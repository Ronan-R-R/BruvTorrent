from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from src.ui.themes import THEMES


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferences")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        form_layout = QFormLayout()

        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        current_theme = self.config.get('theme', 'dark')
        self.theme_combo.setCurrentText(current_theme)
        form_layout.addRow("Theme:", self.theme_combo)

        # Download directory
        self.download_dir_edit = QLineEdit()
        self.download_dir_edit.setText(self.config.get('download_dir', ''))
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_download_dir)
        form_layout.addRow("Download Directory:", self.download_dir_edit)
        form_layout.addRow("", browse_button)

        # Max connections
        self.max_connections_edit = QLineEdit()
        self.max_connections_edit.setText(str(self.config.get('max_connections', 50)))
        form_layout.addRow("Max Connections:", self.max_connections_edit)

        # Start minimized
        self.start_minimized_check = QCheckBox()
        self.start_minimized_check.setChecked(self.config.get('start_minimized', False))
        form_layout.addRow("Start Minimized:", self.start_minimized_check)

        layout.addLayout(form_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_download_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Download Directory")
        if directory:
            self.download_dir_edit.setText(directory)

    def get_selected_theme(self) -> str:
        return self.theme_combo.currentText()

    def accept(self):
        # Save settings to config
        self.config.set('theme', self.get_selected_theme())
        self.config.set('download_dir', self.download_dir_edit.text())
        self.config.set('max_connections', int(self.max_connections_edit.text()))
        self.config.set('start_minimized', self.start_minimized_check.isChecked())
        super().accept()