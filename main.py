"""
Proxy de masking de PII para Langfuse via OpenTelemetry.
Intercepta spans (Protobuf ou JSON) antes de enviá-los ao Langfuse Cloud,
aplicando regras de masking para remover dados sensíveis brasileiros.
"""

import re
import os
import json
import logging
import traceback

import httpx
from fastapi import FastAPI, Request, Response

# Protobuf OTLP
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Langfuse PII Proxy")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Loga todas as requisições recebidas para facilitar debugging."""
    logger.info(
        "REQUEST  method=%s path=%s content-type=%s",
        request.method,
        request.url.path,
        request.headers.get("content-type", "-"),
    )
    response = await call_next(request)
    logger.info(
        "RESPONSE method=%s path=%s status=%s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response

# URL do Langfuse upstream — pode ser sobrescrita por variável de ambiente
LANGFUSE_UPSTREAM = os.getenv(
    "LANGFUSE_UPSTREAM_URL", "https://us.cloud.langfuse.com"
).rstrip("/")


# ---------------------------------------------------------------------------
# Funções de masking
# ---------------------------------------------------------------------------

_PATTERNS = [
    # ------------------------------------------------------------------
    # Cartão de crédito/débito
    # Cobre os principais emissores pelo comprimento e prefixo:
    #   Visa/Master/Elo/Hipercard: 16 dígitos
    #   Amex: 15 dígitos  |  Diners: 14 dígitos
    # Aceita separadores: espaço, hífen ou nada.
    # Aplicado ANTES dos padrões numéricos menores para evitar colisões.
    # ------------------------------------------------------------------
    # Amex  (15 dígitos: 4-6-5)
    (
        re.compile(r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b"),
        "[CARTAO]",
    ),
    # Diners (14 dígitos: 4-6-4)
    (
        re.compile(r"\b3(?:0[0-5]|[68]\d)\d[\s-]?\d{6}[\s-]?\d{4}\b"),
        "[CARTAO]",
    ),
    # Visa / Master / Elo / Hipercard / genérico 16 dígitos (4-4-4-4)
    (
        re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b"),
        "[CARTAO]",
    ),
    # 16 dígitos sem separador (fallback)
    (
        re.compile(r"\b(?:4\d{15}|5[1-5]\d{14}|6(?:011|5\d{2})\d{12}|(?:384|385|386|387)\d{13})\b"),
        "[CARTAO]",
    ),

    # ------------------------------------------------------------------
    # Valores financeiros em BRL
    # Cobre: R$ 1.234,56 / R$1234,56 / R$ 1.234.567,89
    # Também captura valores negativos: R$ -1.234,56
    # ------------------------------------------------------------------
    (
        re.compile(
            r"R\$\s*-?\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?"  # R$ 1.234,56
            r"|\bR\$\s*-?\s*\d+(?:,\d{2})?\b"             # R$ 1234,56
        ),
        "[VALOR]",
    ),
    # Valores em formato numérico com separadores BR quando precedidos de
    # Valores numéricos BR precedidos de palavras-chave financeiras.
    # Captura (keyword)(sep)(valor) e restitui keyword+sep+[VALOR].
    (
        re.compile(
            r"(?i)(saldo|valor|limite|d[eé]bito|cr[eé]dito|pagamento"
            r"|transfer[eê]ncia|tarifa|taxa|parcela|desconto|total"
            r"|subtotal|cobran[cç]a|fatura)(\s*:?\s*)(-?\d{1,3}(?:\.\d{3})*(?:,\d{2})?)"
        ),
        r"\1\2[VALOR]",
    ),

    # ------------------------------------------------------------------
    # Documentos e contatos
    # ------------------------------------------------------------------
    # Números 0800 / 0300 / 0500 / 0900 (sem DDD) — antes do CPF para evitar colisão
    (
        re.compile(r"\b0[89305]00[\s-]?\d{3}[\s-]?\d{4}\b"),
        "[TEL]",
    ),
    # CPF  (123.456.789-09 / 12345678909)
    (re.compile(r"\b\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}\b"), "[CPF]"),
    # CNPJ (12.345.678/0001-90)
    (re.compile(r"\b\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-\s]?\d{2}\b"), "[CNPJ]"),
    # E-mail — captura domínio completo incluindo TLD composto (.com.br)
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b"), "[EMAIL]"),
    # Telefone BR com DDD (+55 11 99999-9999 / (11) 9999-9999)
    (
        re.compile(r"(\+55[\s-]?)?(\(?\d{2}\)?[\s-]?)\d{4,5}[\s-]?\d{4}\b"),
        "[TEL]",
    ),

    # RG  (12.345.678-9)
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}[-]?\d{1,2}\b"), "[RG]"),
    # Nomes próprios: 2+ palavras capitalizadas, opcionalmente separadas por preposição
    (
        re.compile(
            r"\b[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][a-záéíóúàâêôãõç]+"
            r"(?:\s(?:de|da|do|dos|das))?"
            r"(?:\s[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][a-záéíóúàâêôãõç]+)+"
            r"\b"
        ),
        "[NOME]",
    ),
]


def mask_string(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def mask_any(data):
    """Mascara recursivamente dicts, listas e strings."""
    if isinstance(data, str):
        return mask_string(data)
    if isinstance(data, dict):
        return {k: mask_any(v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_any(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Masking Protobuf
# ---------------------------------------------------------------------------

def mask_any_value(av: AnyValue) -> None:
    """Mascara o valor dentro de um AnyValue protobuf in-place."""
    kind = av.WhichOneof("value")
    if kind == "string_value":
        av.string_value = mask_string(av.string_value)
    elif kind == "array_value":
        for v in av.array_value.values:
            mask_any_value(v)
    elif kind == "kvlist_value":
        for kv in av.kvlist_value.values:
            mask_any_value(kv.value)


def mask_protobuf(body: bytes) -> bytes:
    """Deserializa, mascara e re-serializa um ExportTraceServiceRequest."""
    req = ExportTraceServiceRequest()
    req.ParseFromString(body)

    for resource_span in req.resource_spans:
        # Mascara atributos do Resource (ex: host.name, service.instance.id)
        for kv in resource_span.resource.attributes:
            mask_any_value(kv.value)

        for scope_span in resource_span.scope_spans:
            for span in scope_span.spans:
                # Atributos do span
                for kv in span.attributes:
                    mask_any_value(kv.value)

                # Nome do span pode conter PII em algumas integrações
                span.name = mask_string(span.name)

                # Eventos (ex: exceções com stack trace contendo dados)
                for event in span.events:
                    event.name = mask_string(event.name)
                    for kv in event.attributes:
                        mask_any_value(kv.value)

    return req.SerializeToString()


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_simple():
    """Health check interno (ex: Render uptime monitoring)."""
    return {"status": "ok"}


@app.get("/api/public/health")
async def health_langfuse():
    """
    Replica o formato exato do Langfuse health check.
    O IBM Orchestrate chama este endpoint ao configurar a integração e
    espera a resposta no formato {'status': 'OK'} com HTTP 200.
    """
    return {"status": "OK"}


@app.get("/api/public/ready")
async def ready_langfuse():
    """Replica o endpoint de readiness do Langfuse."""
    return {"status": "OK"}


@app.get("/")
async def root():
    """
    Raiz do proxy — retorna status compatível com Langfuse.
    O Orchestrate pode chamar host_health_uri/ durante a validação.
    """
    return {"status": "OK"}


@app.api_route(
    "/api/public/otel/{path:path}",
    methods=["POST", "GET", "PUT", "DELETE"],
)
async def otel_proxy(path: str, request: Request):
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    masked_body = body  # fallback: repassa sem alteração

    try:
        if "application/json" in content_type:
            payload = json.loads(body)
            payload = mask_any(payload)
            masked_body = json.dumps(payload).encode()
            logger.info("Masking aplicado (JSON) — path: %s", path)

        elif "application/x-protobuf" in content_type or "application/protobuf" in content_type:
            masked_body = mask_protobuf(body)
            logger.info("Masking aplicado (Protobuf) — path: %s", path)

        else:
            # Tenta protobuf como default (Orchestrate envia sem content-type explícito)
            try:
                masked_body = mask_protobuf(body)
                logger.info("Masking aplicado (Protobuf/fallback) — path: %s", path)
            except Exception:
                logger.warning("Não foi possível parsear como Protobuf — repassando original")

    except Exception:
        logger.error("Erro no masking:\n%s", traceback.format_exc())
        # Em caso de erro, repassa o body original para não quebrar a observabilidade

    upstream_url = f"{LANGFUSE_UPSTREAM}/api/public/otel/{path}"
    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method=request.method,
            url=upstream_url,
            content=masked_body,
            headers=forward_headers,
            params=dict(request.query_params),
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )


# Rota catch-all para outros endpoints do Langfuse (ex: /api/public/ingestion)
@app.api_route("/{path:path}", methods=["POST", "GET", "PUT", "DELETE", "PATCH"])
async def generic_proxy(path: str, request: Request):
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    masked_body = body
    try:
        if "application/json" in content_type and body:
            payload = json.loads(body)
            payload = mask_any(payload)
            masked_body = json.dumps(payload).encode()
    except Exception:
        pass

    upstream_url = f"{LANGFUSE_UPSTREAM}/{path}"
    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method=request.method,
            url=upstream_url,
            content=masked_body,
            headers=forward_headers,
            params=dict(request.query_params),
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
