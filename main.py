import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from digital_twin_builder.DTlibrary.web_interface import main

if __name__ == "__main__":
    main()
