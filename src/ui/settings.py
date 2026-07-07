"""Preferences dialog."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from src.ui.themes import PALETTES


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(440)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(PALETTES.keys())
        self.theme_combo.setCurrentText(self.config.get('theme'))
        form.addRow("Theme", self.theme_combo)

        self.dir_edit = QLineEdit(self.config.get('download_dir'))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(browse)
        form.addRow("Download folder", dir_row)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(self.config.get('listen_port')))
        form.addRow("Listen port", self.port_spin)

        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(10, 1000)
        self.conn_spin.setValue(int(self.config.get('max_connections')))
        form.addRow("Max connections", self.conn_spin)

        self.minimized_check = QCheckBox()
        self.minimized_check.setChecked(bool(self.config.get('start_minimized')))
        form.addRow("Start minimized", self.minimized_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select download folder", self.dir_edit.text())
        if directory:
            self.dir_edit.setText(directory)

    @property
    def selected_theme(self) -> str:
        return self.theme_combo.currentText()

    def accept(self) -> None:
        self.config.set('theme', self.selected_theme)
        self.config.set('download_dir', self.dir_edit.text())
        self.config.set('listen_port', self.port_spin.value())
        self.config.set('max_connections', self.conn_spin.value())
        self.config.set('start_minimized', self.minimized_check.isChecked())
        super().accept()
