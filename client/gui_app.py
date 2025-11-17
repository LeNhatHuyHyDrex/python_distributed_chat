# client/gui_app.py

import sys

from PyQt6.QtWidgets import QApplication

from .main_window import ChatWindow


def main():
    app = QApplication(sys.argv)
    win = ChatWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
