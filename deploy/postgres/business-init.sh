#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --set=reader_name="$ATLAS_BUSINESS_DB_READER" \
  --set=reader_password="$ATLAS_BUSINESS_DB_READER_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'reader_name', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader_name')
\gexec

ALTER ROLE :"reader_name" SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"POSTGRES_DB" TO :"reader_name";
GRANT USAGE ON SCHEMA public TO :"reader_name";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"reader_name";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"reader_name";
SQL

