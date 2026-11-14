"""PyInstaller entry point. Guard is required by spawned conversion workers."""

from local_pdf_toolkit.app import main

if __name__ == "__main__":
    raise SystemExit(main())
