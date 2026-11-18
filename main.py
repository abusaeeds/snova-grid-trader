"""SNova Grid Trader - start the desktop app.

    python main.py          # normal start (choose Live or Demo on the login screen)
    python main.py --demo   # open with Demo mode already ticked
"""

import sys

from app.gui import App


def main() -> None:
    app = App(demo="--demo" in sys.argv)
    app.mainloop()


if __name__ == "__main__":
    main()
