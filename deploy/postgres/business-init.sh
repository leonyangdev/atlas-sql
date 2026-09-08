#!/bin/sh
set -eu

# 该脚本只在业务库数据卷首次初始化时运行。角色名和密码通过 psql 变量传递，避免把环境值
# 当作 SQL 文本直接拼接。后续迁移还会重复修复授权，以兼容已有命名卷。
psql --set=ON_ERROR_STOP=1 \
  --set=reader_name="$ATLAS_BUSINESS_DB_READER" \
  --set=reader_password="$ATLAS_BUSINESS_DB_READER_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'reader_name', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader_name')
\gexec

-- reader 即使意外获得表级写权限，事务级只读仍会阻止 INSERT/UPDATE/DELETE。
ALTER ROLE :"reader_name" SET default_transaction_read_only = on;
-- public schema 默认 CREATE 会允许普通角色建表，企业项目应显式收回。
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"POSTGRES_DB" TO :"reader_name";
GRANT USAGE ON SCHEMA public TO :"reader_name";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"reader_name";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"reader_name";
SQL
