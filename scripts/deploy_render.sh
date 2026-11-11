#!/usr/bin/env bash
# Deploy OmniResearch OSS Cloud to Render and verify the endpoint end to end.
#
# Usage:
#   export RENDER_API_KEY=rnd_...        # https://dashboard.render.com/account/api-keys
#   bash scripts/deploy_render.sh
#
# The API key is read from the environment only. It is never written to disk,
# never passed as a command-line argument, and never printed.
#
# Steps: create or reuse the service -> wait for the deploy -> probe /healthz
# -> probe MCP initialize and tools/list -> confirm exactly 12 public tools
# -> write a local mcp.json for the verified endpoint.
#
# The generated mcp.json is intentionally NOT committed: the endpoint must be
# live and verified before that file is allowed to exist.
set -euo pipefail

REPO_SLUG='rianprei/omni-research-oss'
SERVICE_NAME='omni-research-oss-mcp'
API='https://api.render.com/v1'
OUT_MCP_JSON='mcp.json'

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die()  { printf 'ERRO: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die 'curl é obrigatório'
command -v python3 >/dev/null 2>&1 || die 'python3 é obrigatório'
[ -n "${RENDER_API_KEY:-}" ] || die 'RENDER_API_KEY não definida. Gere uma em https://dashboard.render.com/account/api-keys'

auth=(-H "Authorization: Bearer ${RENDER_API_KEY}" -H 'Content-Type: application/json')

# json_get <file> <python-expression over `d`>
json_get() {
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print($2)" "$1"
}

# api <METHOD> <PATH> [json-body-file] -> writes the response to a temp file
api() {
  local method="$1" path="$2" body_file="${3:-}"
  local out; out="$(mktemp)"
  if [ -n "$body_file" ]; then
    curl -fsS -X "$method" "${API}${path}" "${auth[@]}" --data-binary "@${body_file}" -o "$out" \
      || { rm -f "$out"; return 1; }
  else
    curl -fsS -X "$method" "${API}${path}" "${auth[@]}" -o "$out" \
      || { rm -f "$out"; return 1; }
  fi
  printf '%s' "$out"
}

log "Verificando a credencial da API..."
if ! api GET '/services?limit=1' >/dev/null; then
  die 'A API do Render rejeitou a credencial. Confira RENDER_API_KEY e a URL da API.'
fi
log 'Credencial aceita.'

# --- reuse or create the service -------------------------------------------
service_id=''
service_url=''
tmp_list="$(mktemp)"
if api GET '/services?limit=100' > "$tmp_list"; then
  service_id="$(json_get "$tmp_list" "next((s['id'] for s in d if s['name']=='$SERVICE_NAME' and s.get('repo','').endswith('$REPO_SLUG')), '')")"
  service_url="$(json_get "$tmp_list" "next((s.get('serviceDetails',{}).get('url','') for s in d if s.get('id')=='$service_id'), '')")"
fi
rm -f "$tmp_list"

if [ -z "$service_id" ]; then
  log "Criando o serviço '${SERVICE_NAME}' a partir de ${REPO_SLUG}..."
  body="$(mktemp)"
  cat > "$body" <<JSON
{
  "service": {
    "name": "${SERVICE_NAME}",
    "repo": "https://github.com/${REPO_SLUG}",
    "branch": "main",
    "runtime": "python",
    "plan": "free",
    "buildCommand": "pip install -r requirements-cloud.txt",
    "startCommand": "uvicorn server.cloud:app --host 0.0.0.0 --port \$PORT",
    "healthCheckPath": "/healthz",
    "autoDeploy": true,
    "envVars": [
      { "key": "PYTHON_VERSION", "value": "3.13.1" },
      { "key": "OMNI_STATE_DIR", "value": "/tmp/omni-research-public" }
    ]
  }
}
JSON
  resp="$(mktemp)"
  if ! api POST '/services' "$body" > "$resp"; then
    rm -f "$body" "$resp"
    die 'A criação do serviço falhou. Verifique se a chave da API tem permissão de escrita e se o repositório está acessível.'
  fi
  service_id="$(json_get "$resp" "d['service']['id']")"
  service_url="$(json_get "$resp" "d['service'].get('serviceDetails',{}).get('url','')")"
  rm -f "$body" "$resp"
  log "Serviço criado: ${service_id}"
else
  log "Serviço já existe: ${service_id}"
fi

# --- wait for a live deploy -------------------------------------------------
log 'Aguardando o deploy ficar live (o plano free pode demorar no primeiro build)...'
status=''
for _ in $(seq 1 120); do
  tmp="$(mktemp)"
  if api GET "/services/${service_id}/deploys" > "$tmp" 2>/dev/null; then
    status="$(json_get "$tmp" "(d[0]['deploy']['status'] if d else 'unknown')")"
  fi
  rm -f "$tmp"
  case "$status" in
    live) log 'Deploy live.'; break ;;
    failed|deactivated|canceled)
      die "O deploy falhou (status: ${status}). Veja os logs no dashboard do Render." ;;
  esac
  sleep 15
done
[ "$status" = 'live' ] || die "O deploy não ficou live a tempo (último status: ${status})."

# --- resolve the public hostname -------------------------------------------
if [ -z "$service_url" ]; then
  tmp="$(mktemp)"
  api GET "/services/${service_id}" > "$tmp" || true
  service_url="$(json_get "$tmp" "d.get('service',{}).get('serviceDetails',{}).get('url','')")"
  rm -f "$tmp"
fi
[ -n "$service_url" ] || die 'Não consegui resolver a URL pública do serviço.'
host="${service_url#https://}"
host="${host%%/*}"
log "Host público: ${host}"

# --- verify /healthz --------------------------------------------------------
log 'Verificando /healthz...'
for _ in $(seq 1 20); do
  if curl -fsS "https://${host}/healthz" >/dev/null 2>&1; then break; fi
  sleep 10
done
curl -fsS "https://${host}/healthz" | head -c 200; echo
log '/healthz respondeu.'

# --- verify the MCP endpoint and the tool count -----------------------------
log 'Verificando o endpoint MCP...'
init="$(curl -fsS "https://${host}/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"deploy-probe","version":"1"}}}')" \
  || die 'O endpoint MCP não respondeu ao initialize.'

echo "$init" | grep -q 'serverInfo' || die 'Resposta MCP inesperada: '"$init"
log 'initialize OK.'

tools="$(curl -fsS "https://${host}/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')" || die 'tools/list falhou.'

count="$(printf '%s' "$tools" | grep -o '"name":"[a-z_]*"' | sort -u | wc -l | tr -d ' ')"
log "tools/list devolveu ${count} ferramentas."
[ "$count" = '12' ] || die "Esperava 12 ferramentas públicas, veio ${count}. Verifique se o serviço está servindo a build correta."

for forbidden in read_document memory_save memory_search; do
  printf '%s' "$tools" | grep -q "\"${forbidden}\"" && die "A ferramenta local-only '${forbidden}' está exposta no serviço público."
done
log 'Nenhuma ferramenta local-only exposta.'

# --- write the submission mcp.json ------------------------------------------
cat > "$OUT_MCP_JSON" <<JSON
{
  "mcpServers": {
    "omni-research-oss": {
      "type": "streamable-http",
      "url": "https://${host}/mcp"
    }
  }
}
JSON
log "mcp.json gerado em ${OUT_MCP_JSON} (não versionado — confirme antes de submeter)."

printf '\n'
log "SERVIÇO NO AR: https://${host}"
log "Endpoint MCP:  https://${host}/mcp"
log 'Próximo passo: submissão no OpenAI Developer Portal (URLs de listagem, verificação de identidade, evidência, demo e casos de revisão).'
