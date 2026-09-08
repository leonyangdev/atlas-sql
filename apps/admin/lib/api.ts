/**
 * AtlasSQL Admin API 客户端
 *
 * 封装对后端 REST API 的 fetch 调用，统一处理错误和类型。
 * 使用 Next.js Server Component 的 fetch（带自动缓存），
 * 客户端交互用 "use client" + useEffect。
 */

/** 后端 API 地址，开发时指向本机 8000 端口 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// ─── 类型定义 ────────────────────────────────────────────────────────────────

export type DataSourceKind = "postgresql" | "mysql" | "bigquery" | "snowflake";
export type DataSourceStatus = "active" | "inactive" | "error";
export type SyncStatus = "pending" | "running" | "succeeded" | "failed";

export interface DataSource {
  id: number;
  slug: string;
  name: string;
  kind: DataSourceKind;
  host: string;
  port: number;
  database_name: string;
  credential_ref: string;
  status: DataSourceStatus;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncJob {
  id: number;
  idempotency_key: string;
  status: SyncStatus;
  retry_count: number;
  tables_discovered: number | null;
  columns_discovered: number | null;
  error_summary: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ColumnMeta {
  id: number;
  column_name: string;
  ordinal_position: number;
  data_type: string;
  is_nullable: boolean;
  is_primary_key: boolean;
  foreign_key_ref: string | null;
  raw_comment: string | null;
  manual_business_name: string | null;
  manual_description: string | null;
  manual_sensitivity: string | null;
  manual_aliases: string | null;
  sample_values: string | null;
  is_deleted: boolean;
}

export interface TableMeta {
  id: number;
  datasource_id: number;
  schema_name: string;
  table_name: string;
  table_type: string;
  row_estimate: number | null;
  raw_comment: string | null;
  manual_business_name: string | null;
  manual_description: string | null;
  manual_domain: string | null;
  manual_grain: string | null;
  manual_authoritative_source: string | null;
  manual_aliases: string | null;
  is_deleted: boolean;
  columns: ColumnMeta[];
}

export interface ConnectionTestResult {
  ok: boolean;
  latency_ms: number;
  error_kind: string | null;
}

// ─── 通用 fetch 包装 ──────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ─── 数据源 API ───────────────────────────────────────────────────────────────

export async function listDatasources(): Promise<DataSource[]> {
  return apiFetch<DataSource[]>("/api/v1/datasources");
}

export async function getDatasource(slug: string): Promise<DataSource> {
  return apiFetch<DataSource>(`/api/v1/datasources/${slug}`);
}

export async function testConnection(
  slug: string,
  adminToken: string
): Promise<ConnectionTestResult> {
  return apiFetch<ConnectionTestResult>(`/api/v1/datasources/${slug}/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
  });
}

export async function triggerSync(
  slug: string,
  adminToken: string
): Promise<{ job_id: number; idempotency_key: string; status: SyncStatus }> {
  return apiFetch(`/api/v1/datasources/${slug}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
  });
}

export async function listSyncJobs(slug: string): Promise<SyncJob[]> {
  return apiFetch<SyncJob[]>(`/api/v1/datasources/${slug}/sync-jobs`);
}

// ─── 元数据 API ───────────────────────────────────────────────────────────────

export async function listTables(params?: {
  datasource_id?: number;
  domain?: string;
  include_deleted?: boolean;
}): Promise<TableMeta[]> {
  const qs = new URLSearchParams();
  if (params?.datasource_id != null) qs.set("datasource_id", String(params.datasource_id));
  if (params?.domain) qs.set("domain", params.domain);
  if (params?.include_deleted) qs.set("include_deleted", "true");
  const query = qs.toString() ? `?${qs}` : "";
  return apiFetch<TableMeta[]>(`/api/v1/metadata/tables${query}`);
}

export async function getTable(tableId: number): Promise<TableMeta> {
  return apiFetch<TableMeta>(`/api/v1/metadata/tables/${tableId}`);
}
