# main.py
import sys
from os.path import dirname, join
sys.path.append(join(dirname(__file__), 'DTlibrary'))

def main():
    # Не создаем интерфейс здесь, так как Streamlit должен управлять этим
    if __name__ == "__main__":
        from digital_twin_builder.DTlibrary.web_interface import DigitalTwinInterface
        interface = DigitalTwinInterface()
        
        # Для Streamlit нам не нужно явно вызывать run()
        # Весь UI управляется через декораторы Streamlit

if __name__ == "__main__":
    # Вместо прямого вызова main(), запускаем Streamlit
    import streamlit.cli as stcli
    import os
    import sys
    
    # Получаем путь к текущему файлу
    script_path = os.path.join(os.path.dirname(__file__), "interfaces", "web_interface.py")
    
    # Запускаем Streamlit с правильными аргументами
    sys.argv = ["streamlit", "run", script_path]
    sys.exit(stcli.main())