import sys
from os.path import dirname, join
import streamlit.cli as stcli
import os
import sys

sys.path.append(join(dirname(__file__), 'DTlibrary'))

def main():
    if __name__ == "__main__":
        from digital_twin_builder.DTlibrary.web_interface import DigitalTwinInterface
        interface = DigitalTwinInterface()

if __name__ == "__main__":
    script_path = os.path.join(os.path.dirname(__file__), "interfaces", "web_interface.py")
    sys.argv = ["streamlit", "run", script_path]
    sys.exit(stcli.main())