import mimetypes
import os

# Força o MIME type correto para arquivos .mjs e .js (necessário para PDF.js)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/javascript", ".mjs", strict=True)
mimetypes.add_type("text/javascript", ".js", strict=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from database import init_db
from routers import pdf, edital, flashcards, questoes, simulados, ciclo, streaks, dashboard, misc

# ============================================================
# CONFIGURAÇÃO
# ============================================================

PDF_ROOT = os.environ.get("PDF_ROOT", "./pdfs")
DB_PATH = "./progress.db"

# Atualizar DB_PATH no módulo database
import database
database.DB_PATH = DB_PATH

# ============================================================
# APP SETUP
# ============================================================

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# INICIALIZAÇÃO DO BANCO
# ============================================================

init_db()

# ============================================================
# CONFIGURAR PDF_ROOT NOS ROUTERS
# ============================================================

pdf.set_pdf_root(PDF_ROOT)

# ============================================================
# INCLUIR ROUTERS
# ============================================================

app.include_router(pdf.router)
app.include_router(edital.router)
app.include_router(flashcards.router)
app.include_router(questoes.router)
app.include_router(simulados.router)
app.include_router(ciclo.router)
app.include_router(streaks.router)
app.include_router(dashboard.router)
app.include_router(misc.router)


# ============================================================
# CORREÇÃO DO MIME TYPE PARA .mjs / .js (PDF.js)
# ============================================================

class FixedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.endswith((".mjs", ".js")):
            response.headers["content-type"] = "application/javascript; charset=utf-8"
        return response


# Monta o frontend com a correção (DEVE SER O ÚLTIMO)
app.mount("/", FixedStaticFiles(directory="../frontend", html=True), name="frontend")
