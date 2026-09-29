"""Application entry point: ``fusecalc [feeder.json]`` or ``python -m fusecalc``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fusecalc import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="fusecalc", description="Fuse sizing, placement, and coordination tool.")
    parser.add_argument("file", nargs="?", type=Path, help="feeder .json file to open")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args, qt_args = parser.parse_known_args(argv[1:])  # leave Qt's own flags alone

    from PySide6.QtWidgets import QApplication

    from fusecalc.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([argv[0], *qt_args])
    app.setApplicationName("Fuse Coordination Tool")
    app.setOrganizationName("ECE6320")
    window = MainWindow()
    if args.file:
        window.open_path(args.file, check_saved=False)
    window.show()
    window.view.fit()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
