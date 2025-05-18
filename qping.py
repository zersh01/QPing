#!/usr/bin/env python3
# qping.py
import sys
import os
from main import PingMonitor
from PyQt6.QtWidgets import QApplication

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PingMonitor()
    window.show()
    sys.exit(app.exec())
