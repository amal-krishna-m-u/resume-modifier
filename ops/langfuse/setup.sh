#!/usr/bin/env bash
# Writes ops/langfuse/.env with fresh random secrets, and prints the two lines
# resume-tailor needs. Refuses to overwrite an existing .env.
set -euo pipefail
cd "$(dirname "$0")"
[ -e .env ] && { echo ".env exists; delete it first if you really want new secrets" >&2; exit 1; }
r() { openssl rand -hex "${1:-16}"; }
cat > .env <<EOF
POSTGRES_PASSWORD=$(r)
CLICKHOUSE_PASSWORD=$(r)
MINIO_ROOT_PASSWORD=$(r)
REDIS_AUTH=$(r)
SALT=$(r)
ENCRYPTION_KEY=$(r 32)
NEXTAUTH_SECRET=$(r)
LANGFUSE_PUBLIC_KEY=pk-lf-$(r 12)
LANGFUSE_SECRET_KEY=sk-lf-$(r 12)
LANGFUSE_USER_EMAIL=owner@localhost.invalid
LANGFUSE_USER_PASSWORD=$(r 12)
EOF
chmod 600 .env
echo "Created ops/langfuse/.env (gitignored). Next:"
echo "  docker compose up -d"
echo "  export LANGFUSE_PUBLIC_KEY=\$(grep ^LANGFUSE_PUBLIC_KEY .env | cut -d= -f2)"
echo "  export LANGFUSE_SECRET_KEY=\$(grep ^LANGFUSE_SECRET_KEY .env | cut -d= -f2)"
echo "  set [observability] langfuse = true in resume-tailor.toml, then: rt trace status"
echo "Login at http://localhost:3000 — $(grep ^LANGFUSE_USER_EMAIL .env | cut -d= -f2) / password in .env"
