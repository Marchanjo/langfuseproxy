# Langfuse PII Proxy

Proxy HTTP que intercepta os spans OpenTelemetry enviados pelo IBM Orchestrate
ao Langfuse Cloud, mascarando PII (CPF, CNPJ, RG, e-mail, telefone, nomes)
antes do envio.

```
IBM Orchestrate → este proxy (Render) → Langfuse Cloud
```

## Dados mascarados

| Tipo       | Exemplo original      | Após masking  |
|------------|-----------------------|---------------|
| CPF        | 123.456.789-09        | [CPF]         |
| CNPJ       | 12.345.678/0001-90    | [CNPJ]        |
| E-mail     | joao@empresa.com.br   | [EMAIL]       |
| Telefone   | (11) 99999-9999       | [TEL]         |
| RG         | 12.345.678-9          | [RG]          |
| Nome       | João da Silva         | [NOME]        |

## Deploy no Render

### 1. Suba o código no GitHub

```bash
git init
git add .
git commit -m "langfuse pii proxy"
gh repo create langfuse-pii-proxy --public --push   # ou crie pelo GitHub e faça push
```

### 2. Crie o Web Service no Render

1. Acesse https://render.com → **New → Web Service**
2. Conecte o repositório GitHub criado acima
3. Render detecta automaticamente o `render.yaml` e preenche as configurações
4. Clique em **Create Web Service**
5. Aguarde o deploy — ao final você terá uma URL como:
   `https://langfuse-pii-proxy.onrender.com`

> **Atenção:** o plano **free** do Render hiberna após 15 min sem tráfego.
> Se precisar que o proxy esteja sempre ativo, use o plano **Starter** (~$7/mês).

### 3. Configure o IBM Orchestrate para apontar para o proxy

Crie o arquivo `langfuse-config.yml`:

```yaml
spec_version: v1
kind: langfuse
api_key: sk-lf-SEU_SECRET_KEY
url: https://langfuse-pii-proxy.onrender.com/api/public/otel
host_health_uri: https://langfuse-pii-proxy.onrender.com
config_json:
  public_key: pk-lf-SEU_PUBLIC_KEY
```

Aplique:

```bash
orchestrate settings observability langfuse configure --config-file=langfuse-config.yml
```

### 4. Teste

```bash
# Health check do proxy
curl https://langfuse-pii-proxy.onrender.com/health
# → {"status":"ok"}
```

Dispare um agente no Orchestrate e verifique nos traces do Langfuse
que CPFs, nomes e e-mails aparecem mascarados.

## Variáveis de ambiente

| Variável              | Padrão                            | Descrição                        |
|-----------------------|-----------------------------------|----------------------------------|
| `LANGFUSE_UPSTREAM_URL` | `https://us.cloud.langfuse.com` | URL do Langfuse (US ou EU)       |

Altere pelo dashboard do Render em **Environment → Environment Variables**.

## Estrutura

```
main.py           # proxy FastAPI com masking Protobuf + JSON
requirements.txt  # dependências
render.yaml       # blueprint do Render
```
