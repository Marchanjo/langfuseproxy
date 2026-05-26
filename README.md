# Langfuse PII Proxy

Proxy HTTP que intercepta os spans OpenTelemetry enviados pelo IBM Orchestrate
ao Langfuse Cloud, mascarando PII (CPF, CNPJ, RG, e-mail, telefone, nomes,
cartões de crédito e valores financeiros) antes do envio.

```
IBM Orchestrate → este proxy (Render) → Langfuse Cloud
```

## Dados mascarados

### Documentos e contatos

| Tipo     | Exemplo original    | Após masking |
|----------|---------------------|--------------|
| CPF      | 123.456.789-09      | [CPF]        |
| CNPJ     | 12.345.678/0001-90  | [CNPJ]       |
| RG       | 12.345.678-9        | [RG]         |
| E-mail   | joao@empresa.com.br | [EMAIL]      |
| Telefone | (11) 99999-9999     | [TEL]        |
| Nome     | João da Silva       | [NOME]       |

### Cartões de crédito/débito

| Bandeira                        | Exemplo original    | Após masking |
|---------------------------------|---------------------|--------------|
| Visa/Master/Elo — com espaço    | 4111 1111 1111 1111 | [CARTAO]     |
| Visa/Master/Elo — com hífen     | 4111-1111-1111-1111 | [CARTAO]     |
| Visa/Master/Elo — sem separador | 4111111111111111    | [CARTAO]     |
| Amex (15 dígitos)               | 3714 496353 98431   | [CARTAO]     |
| Diners (14 dígitos)             | 3056 930009 0259    | [CARTAO]     |

### Valores financeiros

| Formato                       | Exemplo original  | Após masking    |
|-------------------------------|-------------------|-----------------|
| R$ com separador de milhar    | R$ 1.234,56       | [VALOR]         |
| R$ sem separador de milhar    | R$750,00          | [VALOR]         |
| R$ negativo                   | R$ -200,50        | [VALOR]         |
| Após palavra-chave financeira | Saldo: 3.200,00   | Saldo: [VALOR]  |
| Após palavra-chave financeira | Valor: 150,00     | Valor: [VALOR]  |

Palavras-chave reconhecidas: `saldo`, `valor`, `limite`, `débito`, `crédito`,
`pagamento`, `transferência`, `tarifa`, `taxa`, `parcela`, `desconto`, `total`,
`subtotal`, `cobrança`, `fatura`.

> **Não mascarados** (intencionalmente): anos (`2024`), datas (`12/2027`) e
> números sem contexto financeiro explícito.

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
