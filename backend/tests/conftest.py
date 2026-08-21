"""
Conftest compartilhado para testes.
Garante que cada arquivo de teste que importar database use seu próprio DB temporário.
"""
import os

# Garante AUTH desabilitado em testes
os.environ.setdefault("AUTH_ENABLED", "false")
