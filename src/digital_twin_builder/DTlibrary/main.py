from .interfaces.web_interface import DigitalTwinInterface
import streamlit as st

def main():
    interface = DigitalTwinInterface()
    interface.run()

if __name__ == "__main__":
    main()