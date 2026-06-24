from __future__ import annotations
import sys
from .common import QApplication
from .window import EditorWindow


def main():
    """
    Einstiegspunkt des Editors: erstellt die ``QApplication``, zeigt das
    ``EditorWindow`` an und startet die Ereignisschleife.

    The editor entry point: create the ``QApplication``, show the
    ``EditorWindow`` and run the event loop.
    """
    app = QApplication(sys.argv)
    win = EditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
