#!/usr/bin/python3
"""QPing launcher"""
import sys

sys.path.insert(0, "/usr/lib/python3/dist-packages/qping")

from PyQt6.QtWidgets import QApplication
from main import PingMonitor

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PingMonitor()
    window.show()
    sys.exit(app.exec())
