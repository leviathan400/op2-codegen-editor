from __future__ import annotations
import sys
from .common import QApplication
from .window import EditorWindow


def main():
    app = QApplication(sys.argv)
    win = EditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
