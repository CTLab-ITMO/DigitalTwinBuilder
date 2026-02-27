from .agents import *
from .sensors import *
from .cores import *

# Модуль interfaces опционален и может отсутствовать в минимальной сборке.
try:
    from .interfaces import *
except Exception:
    # Интерфейсы UI недоступны, но ядро (оркестратор, агенты, сенсоры) может работать без них.
    pass
