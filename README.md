# Leitor PDF

Aplicação web para leitura de PDFs organizados em pastas, com rastreamento de progresso por arquivo e por pasta.

## Início rápido (Windows)

Basta dar **duplo-clique** em `Setup-e-Iniciar.cmd`.

O script faz tudo automaticamente:

1. Verifica se o Python 3.10+ está instalado — se não estiver, instala via `winget`.
2. Verifica e instala o `pip` se necessário.
3. Instala as dependências Python (`fastapi`, `uvicorn`, `pypdf`, `python-multipart`).
4. Libera a porta 8000 caso esteja ocupada.
5. Inicia o servidor e abre o navegador em [http://localhost:8000](http://localhost:8000).

Cada etapa exibe o status no terminal (`[OK]`, `[AVISO]`, `[ERRO]`).

## Instalação manual

Caso prefira fazer manualmente:

### Requisitos

- Python 3.10+
- pip

### Passos

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Acesse no navegador: [http://localhost:8000](http://localhost:8000)

## Configuração

Por padrão, a aplicação lê os PDFs da pasta `backend/pdfs/`.

Para usar outra pasta, defina a variável de ambiente `PDF_ROOT`:

```powershell
# Windows (PowerShell)
$env:PDF_ROOT = "C:\caminho\para\seus\pdfs"
```

```bash
# Linux / macOS
export PDF_ROOT="/caminho/para/seus/pdfs"
```

A estrutura de subpastas é lida automaticamente e exibida como árvore na interface.

## Funcionalidades

- Lista PDFs organizados por pastas com colapso/expansão
- Barra de progresso por PDF (páginas lidas / total)
- Barra de progresso por pasta (agregado dos PDFs internos)
- Badge ✓ ao concluir um PDF ou pasta inteira
- Ao abrir um PDF, retoma automaticamente na última página lida
- Progresso salvo automaticamente ao trocar de página e ao fechar
- Visualizador integrado com PDF.js

## Estrutura do projeto

```
LeitorPDF/
├── Setup-e-Iniciar.cmd   # Duplo-clique para iniciar (chama o .ps1)
├── Setup-e-Iniciar.ps1   # Script de setup automático e inicialização
├── Estudar.cmd            # Atalho legado de inicialização rápida
├── README.md
├── backend/
│   ├── main.py            # API FastAPI + servidor de arquivos estáticos
│   ├── requirements.txt   # Dependências Python
│   ├── progress.db        # SQLite gerado automaticamente na primeira execução
│   └── pdfs/              # Coloque seus PDFs aqui (ou configure PDF_ROOT)
│       └── ...
└── frontend/
    ├── index.html         # Lista de PDFs com progresso
    ├── viewer.html        # Visualizador com tracking de página
    └── pdfjs/             # PDF.js embutido para renderização precisa
        └── ...
```

## Observações

- O visualizador usa PDF.js embutido para tracking preciso de página em todos os navegadores.
- O progresso é armazenado localmente em `progress.db` (SQLite) na pasta `backend/`.
- O banco é criado automaticamente na primeira execução — não requer configuração.
