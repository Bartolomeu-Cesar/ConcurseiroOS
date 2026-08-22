"""
Conftest compartilhado para testes.
Garante que cada arquivo de teste que importar database use seu próprio DB temporário.
A isolação real é feita via dependency_overrides em cada módulo de teste.
"""
import os
import sys

# Garante AUTH desabilitado em testes
os.environ.setdefault("AUTH_ENABLED", "false")

# Ajustar path para imports (garante que backend/ está no sys.path)
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
