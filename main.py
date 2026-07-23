"""Entry point: creates the QApplication, a pyrealsense2 context, loads
settings.yaml (read-only defaults) and gui_state.json (the GUI's own
persisted choices), and shows the MainWindow wizard."""

import sys

import pyrealsense2 as rs
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from state.gui_state import load_gui_state
from settings import load_settings


def main():
    app = QApplication(sys.argv)
    ctx = rs.context()
    gui_state = load_gui_state()
    settings = load_settings()

    window = MainWindow(ctx, gui_state, settings)
    window.resize(1200, 800)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
