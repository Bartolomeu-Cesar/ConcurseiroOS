"""Integração com Mercado Pago para pagamento via PIX.

Fluxo:
1. POST /api/pagamentos/pix/criar → Cria cobrança PIX no MP → retorna QR Code + copia-e-cola
2. Frontend exibe QR Code e aguarda confirmação
3. POST /api/pagamentos/webhook → MP notifica pagamento → credita automaticamente
4. GET /api/pagamentos/status/{id} → Verifica status do pagamento

Configuração via variáveis de ambiente:
- MERCADO_PAGO_ACCESS_TOKEN: Token de produção/sandbox
- MERCADO_PAGO_WEBHOOK_SECRET: Para validar webhooks (opcional)
- PIX_CHAVE: Chave PIX para recebimento (telefone, email, CPF ou aleatória)
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from plans import CREDIT_CONFIG

from database import get_db_session
from logger import log

router = APIRouter(prefix="/api/pagamentos", tags=["Pagamentos"])

# ==================== CONFIGURAÇÃO ====================

MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "")
MERCADO_PAGO_WEBHOOK_SECRET = os.environ.get("MERCADO_PAGO_WEBHOOK_SECRET", "")
PIX_CHAVE = os.environ.get("PIX_CHAVE", "99981368527")  # Chave PIX padrão (telefone)

# Tentar importar SDK
try:
    import mercadopago
    MP_AVAILABLE = True
except ImportError:
    MP_AVAILABLE = False
    log.warning("mercadopago SDK não instalado - pagamentos desabilitados")


def _get_mp_sdk():
    """Retorna instância do SDK Mercado Pago configurada."""
    if not MP_AVAILABLE:
        raise HTTPException(status_code=503, detail="Sistema de pagamento indisponível")
    if not MERCADO_PAGO_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="Token do Mercado Pago não configurado. Configure MERCADO_PAGO_ACCESS_TOKEN.")
    return mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)


# ==================== ENDPOINTS ====================

@router.post("/pix/criar", summary="Criar cobrança PIX via Mercado Pago",
             description="Gera QR Code PIX para pagamento de créditos. Retorna imagem do QR e código copia-e-cola.")
def criar_pix(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria pagamento PIX no Mercado Pago.

    body: {creditos: int, email: str (opcional)}
    """
    creditos = body.get("creditos", 10)
    email = body.get("email", "")

    if creditos < 1:
        raise HTTPException(status_code=400, detail="Mínimo 1 crédito")

    # Calcular valor (preços configuráveis via admin)
    from plans import get_creditos_precos
    precos = get_creditos_precos()
    if creditos in precos:
        valor = precos[creditos]
    else:
        # Valor proporcional baseado no preço unitário com desconto progressivo
        valor = round(creditos * 4.90 * max(0.5, 1 - creditos * 0.005), 2)

    dias = creditos * CREDIT_CONFIG["dias_por_credito"]

    # Criar pagamento no Mercado Pago
    sdk = _get_mp_sdk()
    payment_data = {
        "transaction_amount": valor,
        "description": f"ConcurseiroOS: {creditos} créditos ({dias} dias Premium)",
        "payment_method_id": "pix",
        "payer": {
            "email": email or f"user{user_id}@concurseiroos.app",
        },
        "metadata": {
            "user_id": user_id,
            "creditos": creditos,
            "tipo": "creditos",
        },
        # Expiração do PIX: 30 minutos
        "date_of_expiration": (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000-03:00"),
    }

    payment_response = sdk.payment().create(payment_data)
    payment = payment_response.get("response", {})

    if payment_response.get("status") not in (200, 201):
        log.error(f"Erro ao criar PIX: {payment_response}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar pagamento: {payment.get('message', 'Erro desconhecido')}"
        )

    # Extrair dados do PIX
    pix_info = payment.get("point_of_interaction", {}).get("transaction_data", {})
    qr_code = pix_info.get("qr_code", "")
    qr_code_base64 = pix_info.get("qr_code_base64", "")
    ticket_url = pix_info.get("ticket_url", "")

    payment_id = payment.get("id")

    # Salvar pagamento pendente no banco
    try:
        conn.execute("""
            INSERT INTO pagamentos (user_id, payment_id, tipo, creditos, valor, status, created_at)
            VALUES (?, ?, 'pix_creditos', ?, ?, 'pending', ?)
        """, (user_id, str(payment_id), creditos, valor, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception as e:
        log.warning(f"Erro ao salvar pagamento no banco: {e}")

    log.info(f"PIX criado: user={user_id} creditos={creditos} valor=R${valor} payment_id={payment_id}")

    return {
        "ok": True,
        "payment_id": payment_id,
        "valor": valor,
        "creditos": creditos,
        "dias": dias,
        "pix": {
            "qr_code": qr_code,           # Código copia-e-cola
            "qr_code_base64": qr_code_base64,  # Imagem QR em base64
            "ticket_url": ticket_url,      # URL do ticket MP
        },
        "expira_em": "30 minutos",
        "mensagem": f"Escaneie o QR Code ou copie o código PIX. R${valor:.2f} por {creditos} créditos ({dias} dias).",
    }


@router.post("/pix/vitalicio", summary="Criar cobrança PIX para plano Vitalício",
             description="Gera QR Code PIX para pagamento único do plano Vitalício (R$97). Só disponível durante janela de venda.")
def criar_pix_vitalicio(
    body: dict = Body(default={}),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria pagamento PIX para plano Vitalício.

    Verifica se a janela de venda está aberta antes de permitir a compra.
    body: {email: str (opcional)}
    """
    from plans import get_vitalicio_preco, is_vitalicio_disponivel

    # Verificar janela de venda
    janela = is_vitalicio_disponivel()
    if not janela["disponivel"]:
        raise HTTPException(status_code=403, detail=janela["motivo"])

    # Verificar se já é vitalício
    user = conn.execute("SELECT plano FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and user[0] == "ilimitado":
        raise HTTPException(status_code=400, detail="Você já possui o plano Vitalício!")

    email = body.get("email", "")
    valor = get_vitalicio_preco()  # Preço configurável (default R$97)

    # Criar pagamento no Mercado Pago
    sdk = _get_mp_sdk()
    payment_data = {
        "transaction_amount": valor,
        "description": "ConcurseiroOS: Plano Vitalício — Acesso permanente",
        "payment_method_id": "pix",
        "payer": {
            "email": email or f"user{user_id}@concurseiroos.app",
        },
        "metadata": {
            "user_id": user_id,
            "tipo": "vitalicio",
        },
        "date_of_expiration": (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000-03:00"),
    }

    payment_response = sdk.payment().create(payment_data)
    payment = payment_response.get("response", {})

    if payment_response.get("status") not in (200, 201):
        log.error(f"Erro ao criar PIX vitalício: {payment_response}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar pagamento: {payment.get('message', 'Erro desconhecido')}"
        )

    pix_info = payment.get("point_of_interaction", {}).get("transaction_data", {})
    qr_code = pix_info.get("qr_code", "")
    qr_code_base64 = pix_info.get("qr_code_base64", "")
    ticket_url = pix_info.get("ticket_url", "")
    payment_id = payment.get("id")

    # Salvar pagamento pendente
    try:
        conn.execute("""
            INSERT INTO pagamentos (user_id, payment_id, tipo, creditos, valor, status, created_at)
            VALUES (?, ?, 'pix_vitalicio', 0, ?, 'pending', ?)
        """, (user_id, str(payment_id), valor, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception as e:
        log.warning(f"Erro ao salvar pagamento vitalício: {e}")

    log.info(f"PIX vitalício criado: user={user_id} valor=R${valor} payment_id={payment_id}")

    return {
        "ok": True,
        "payment_id": payment_id,
        "valor": valor,
        "tipo": "vitalicio",
        "pix": {
            "qr_code": qr_code,
            "qr_code_base64": qr_code_base64,
            "ticket_url": ticket_url,
        },
        "expira_em": "30 minutos",
        "mensagem": f"Escaneie o QR Code ou copie o código PIX. R${valor:.2f} — Acesso Vitalício permanente!",
    }


@router.get("/status/{payment_id}", summary="Verificar status do pagamento")
def status_pagamento(
    payment_id: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Verifica status do pagamento no Mercado Pago."""
    sdk = _get_mp_sdk()

    payment_response = sdk.payment().get(int(payment_id))
    payment = payment_response.get("response", {})

    status = payment.get("status", "unknown")
    status_detail = payment.get("status_detail", "")

    # Se aprovado e ainda não creditado, creditar agora
    if status == "approved":
        _creditar_pagamento(conn, user_id, payment_id, payment)

    status_map = {
        "approved": "✅ Pagamento aprovado!",
        "pending": "⏳ Aguardando pagamento...",
        "in_process": "⏳ Processando...",
        "rejected": "❌ Pagamento rejeitado",
        "cancelled": "❌ Pagamento cancelado",
        "refunded": "↩️ Pagamento estornado",
    }

    return {
        "payment_id": payment_id,
        "status": status,
        "status_label": status_map.get(status, status),
        "status_detail": status_detail,
        "aprovado": status == "approved",
    }


@router.post("/webhook", summary="Webhook do Mercado Pago (notificação de pagamento)")
async def webhook_mercadopago(request: Request, conn=Depends(get_db_session)):
    """Recebe notificações do Mercado Pago quando um pagamento é aprovado.

    O MP envia POST com:
    - action: "payment.created" ou "payment.updated"
    - data.id: ID do pagamento
    - Headers: x-signature (HMAC-SHA256), x-request-id
    """
    # === VALIDAÇÃO HMAC ===
    if MERCADO_PAGO_WEBHOOK_SECRET:
        x_signature = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")

        if not x_signature:
            log.warning("Webhook sem x-signature — rejeitado")
            return {"ok": True}  # Retorna 200 para não causar retries, mas não processa

        # Extrair ts e v1 do header: "ts=1704908010,v1=abc123..."
        parts = {}
        for part in x_signature.split(","):
            kv = part.strip().split("=", 1)
            if len(kv) == 2:
                parts[kv[0]] = kv[1]

        ts = parts.get("ts", "")
        received_hash = parts.get("v1", "")

        if not ts or not received_hash:
            log.warning("Webhook x-signature malformado — rejeitado")
            return {"ok": True}

        # Extrair data.id da query string (MP envia como ?data.id=XXX) ou do body
        data_id = request.query_params.get("data.id", "")

        # Montar template para HMAC: "id:{data_id};request-id:{x_request_id};ts:{ts};"
        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

        # Calcular HMAC-SHA256
        expected_hash = hmac.new(
            MERCADO_PAGO_WEBHOOK_SECRET.encode(),
            manifest.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            log.warning(f"Webhook HMAC inválido — rejeitado (data_id={data_id})")
            return {"ok": True}  # 200 para evitar retries, mas não credita

        log.info(f"Webhook HMAC validado OK (data_id={data_id})")

    try:
        body = await request.json()
    except Exception:
        return {"ok": True}  # Sempre retornar 200 para o MP não reenviar

    action = body.get("action", "")
    data = body.get("data", {})
    payment_id = data.get("id") or body.get("id")

    log.info(f"Webhook MP: action={action} payment_id={payment_id}")

    if not payment_id:
        return {"ok": True}

    # Verificar no MP se o pagamento foi aprovado
    try:
        sdk = _get_mp_sdk()
        payment_response = sdk.payment().get(int(payment_id))
        payment = payment_response.get("response", {})

        if payment.get("status") == "approved":
            metadata = payment.get("metadata", {})
            webhook_user_id = metadata.get("user_id")
            if webhook_user_id:
                _creditar_pagamento(conn, webhook_user_id, str(payment_id), payment)
                log.info(f"Webhook: creditado user={webhook_user_id} payment={payment_id}")
    except Exception as e:
        log.error(f"Webhook erro: {e}")

    return {"ok": True}


@router.get("/historico", summary="Histórico de pagamentos do usuário")
def historico_pagamentos(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna histórico de pagamentos do usuário."""
    try:
        rows = conn.execute("""
            SELECT payment_id, tipo, creditos, valor, status, created_at
            FROM pagamentos WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 20
        """, (user_id,)).fetchall()
        return {"items": [dict(r) for r in rows]}
    except Exception:
        return {"items": []}


# ==================== FUNÇÕES AUXILIARES ====================

def _creditar_pagamento(conn, user_id: int, payment_id: str, payment: dict):
    """Credita os créditos do pagamento aprovado ao usuário E auto-ativa Premium.

    Fluxo: PIX aprovado → créditos adicionados → créditos convertidos em dias Premium automaticamente.
    O estudante não precisa ativar manualmente — paga e já está Premium.
    """
    # Verificar se já foi creditado (evitar duplicidade)
    try:
        existing = conn.execute(
            "SELECT status FROM pagamentos WHERE payment_id = ? AND user_id = ?",
            (payment_id, user_id)
        ).fetchone()
        if existing and existing[0] == "approved":
            return  # Já creditado
    except Exception:
        pass

    metadata = payment.get("metadata", {})

    # === TIPO VITALÍCIO: Ativar plano ilimitado diretamente ===
    if metadata.get("tipo") == "vitalicio":
        conn.execute(
            "UPDATE users SET plano = 'ilimitado', plano_expira = 'vitalicio' WHERE id = ?",
            (user_id,)
        )
        try:
            conn.execute(
                "UPDATE pagamentos SET status = 'approved' WHERE payment_id = ? AND user_id = ?",
                (payment_id, user_id)
            )
        except Exception:
            pass
        conn.commit()
        log.info(f"Plano Vitalício ativado: user={user_id} via PIX #{payment_id}")
        return

    # === TIPO CRÉDITOS: Converter em dias Premium ===
    creditos = metadata.get("creditos", 0)

    if not creditos:
        # Tentar calcular pelo valor
        valor = payment.get("transaction_amount", 0)
        # Reverso: encontrar quantidade pelo valor
        for qtd, preco in CREDIT_CONFIG["precos"].items():
            if abs(preco - valor) < 0.01:
                creditos = qtd
                break
        if not creditos and valor > 0:
            creditos = max(1, int(valor / 4.90))

    if creditos < 1:
        return

    # Buscar saldo atual e plano
    row = conn.execute(
        "SELECT creditos_saldo, plano, plano_expira FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    saldo_anterior = row[0] if row and row[0] else 0

    # Adicionar ao saldo
    try:
        conn.execute(
            "UPDATE users SET creditos_saldo = COALESCE(creditos_saldo, 0) + ? WHERE id = ?",
            (creditos, user_id)
        )
    except Exception:
        pass

    # Atualizar status do pagamento
    try:
        conn.execute(
            "UPDATE pagamentos SET status = 'approved' WHERE payment_id = ? AND user_id = ?",
            (payment_id, user_id)
        )
    except Exception:
        pass

    # Registrar no histórico de créditos
    saldo_posterior = saldo_anterior + creditos
    try:
        conn.execute("""
            INSERT INTO creditos_historico (user_id, tipo, quantidade, saldo_anterior, saldo_posterior, motivo, created_at)
            VALUES (?, 'pagamento_pix', ?, ?, ?, ?, ?)
        """, (user_id, creditos, saldo_anterior, saldo_posterior,
              f"PIX aprovado (MP #{payment_id})", datetime.now(timezone.utc).isoformat()))
    except Exception:
        pass

    # === AUTO-ATIVAR PREMIUM ===
    # Converter TODOS os créditos recém-comprados em dias de acesso Premium automaticamente.
    dias = creditos * CREDIT_CONFIG["dias_por_credito"]

    # Determinar data base: se já é premium ativo, estender; senão, partir de agora
    plano_atual = row[1] if row else "free"
    plano_expira = row[2] if row else ""

    if plano_atual == "premium" and plano_expira and plano_expira not in ("vitalicio", "vitalício", "lifetime"):
        try:
            base = datetime.fromisoformat(plano_expira)
            if base > datetime.now(timezone.utc):
                nova_expira = (base + timedelta(days=dias)).isoformat()
            else:
                nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()
        except (ValueError, TypeError):
            nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()
    elif plano_atual == "ilimitado":
        # Já é vitalício, créditos ficam no saldo como reserva
        nova_expira = None
    else:
        nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()

    if nova_expira:
        # Ativar premium e debitar créditos usados
        conn.execute(
            "UPDATE users SET plano = 'premium', plano_expira = ?, creditos_saldo = 0 WHERE id = ?",
            (nova_expira, user_id)
        )
        # Registrar ativação no histórico
        try:
            conn.execute("""
                INSERT INTO creditos_historico (user_id, tipo, quantidade, saldo_anterior, saldo_posterior, motivo, created_at)
                VALUES (?, 'ativacao_auto', ?, ?, 0, ?, ?)
            """, (user_id, -creditos, saldo_posterior,
                  f"Auto-ativação: {dias} dias Premium via PIX #{payment_id}",
                  datetime.now(timezone.utc).isoformat()))
        except Exception:
            pass
        log.info(f"Auto-ativação Premium: user={user_id} +{dias} dias (créditos={creditos}) via PIX #{payment_id}")
    else:
        log.info(f"Créditos adicionados (user já vitalício): user={user_id} +{creditos} via PIX #{payment_id}")

    conn.commit()
