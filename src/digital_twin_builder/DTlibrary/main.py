import sys
from os.path import dirname, join
sys.path.append(join(dirname(__file__), 'DTlibrary'))

from interfaces.web_interface import DigitalTwinInterface

def main():
    interface = DigitalTwinInterface()
    interface.run()

if __name__ == "__main__":
    main()