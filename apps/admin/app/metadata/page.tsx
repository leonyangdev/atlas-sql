/**
 * 元数据浏览页（表列表）
 *
 * 支持按 datasource_id 和 domain 过滤。
 * 点击表行跳转到表详情。
 */

import Link from "next/link";
import { listTables } from "../../lib/api";
import type { TableMeta } from "../../lib/api";

interface Props {
  searchParams: Promise<{
    datasource_id?: string;
    domain?: string;
    include_deleted?: string;
  }>;
}

// 业务域常量，与 catalog.py 中的 Domain Literal 对应
const DOMAINS = ["store", "product", "customer", "sales", "inventory", "finance", "marketing"];

async function TableList({
  datasourceId,
  domain,
  includeDeleted,
}: {
  datasourceId?: number;
  domain?: string;
  includeDeleted?: boolean;
}) {
  let tables: TableMeta[] = [];
  let error: string | null = null;

  try {
    tables = await listTables({
      datasource_id: datasourceId,
      domain: domain || undefined,
      include_deleted: includeDeleted,
    });
  } catch (e) {
    error = e instanceof Error ? e.message : "未知错误";
  }

  if (error) {
    return (
      <div className="card error-card" role="alert">
        <strong>无法加载元数据</strong>
        <p>{error}</p>
        <p className="hint">请确认后端 API 已启动，并已执行过至少一次元数据同步。</p>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className="card empty-card" role="status">
        <strong>暂无表元数据</strong>
        <p>
          请先登记数据源并触发同步，或在
          <Link href="/datasources"> 数据源管理</Link> 页面触发同步任务。
        </p>
      </div>
    );
  }

  return (
    <table className="data-table" aria-label="表元数据列表">
      <thead>
        <tr>
          <th>表名</th>
          <th>业务名称</th>
          <th>业务域</th>
          <th>类型</th>
          <th>行数估算</th>
          <th>粒度</th>
          <th aria-label="操作" />
        </tr>
      </thead>
      <tbody>
        {tables.map((t) => (
          <tr key={t.id} className={t.is_deleted ? "row-deleted" : ""}>
            <td>
              <code>{t.table_name}</code>
            </td>
            <td>{t.manual_business_name ?? <span className="empty-hint">—</span>}</td>
            <td>
              {t.manual_domain ? (
                <Link href={`/metadata?domain=${t.manual_domain}`} className="domain-tag">
                  {t.manual_domain}
                </Link>
              ) : (
                <span className="empty-hint">—</span>
              )}
            </td>
            <td>{t.table_type}</td>
            <td>{t.row_estimate?.toLocaleString() ?? "—"}</td>
            <td className="grain-cell">
              {t.manual_grain ? (
                <span title={t.manual_grain}>{t.manual_grain.slice(0, 40)}…</span>
              ) : (
                <span className="empty-hint">—</span>
              )}
            </td>
            <td>
              <Link href={`/metadata/${t.id}`} className="link-btn">
                详情
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default async function MetadataPage({ searchParams }: Props) {
  const params = await searchParams;
  const datasourceId = params.datasource_id ? Number(params.datasource_id) : undefined;
  const domain = params.domain;
  const includeDeleted = params.include_deleted === "true";

  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/">← 控制台</Link>
        </p>
        <h1>
          {domain ? `${domain} 域元数据` : "元数据浏览"}
        </h1>
        <p>已采集的表结构，可按业务域过滤。点击表名查看字段详情和人工注释。</p>
      </header>

      {/* 域过滤导航 */}
      <nav className="domain-nav" aria-label="业务域过滤">
        <Link
          href="/metadata"
          className={`domain-btn ${!domain ? "active" : ""}`}
        >
          全部
        </Link>
        {DOMAINS.map((d) => (
          <Link
            key={d}
            href={`/metadata?domain=${d}${datasourceId ? `&datasource_id=${datasourceId}` : ""}`}
            className={`domain-btn ${domain === d ? "active" : ""}`}
          >
            {d}
          </Link>
        ))}
      </nav>

      {/* 过滤状态提示 */}
      {datasourceId && (
        <p className="filter-badge">
          数据源 ID = {datasourceId}
          <Link href={domain ? `/metadata?domain=${domain}` : "/metadata"} className="clear-filter">
            ✕ 清除
          </Link>
        </p>
      )}

      <TableList datasourceId={datasourceId} domain={domain} includeDeleted={includeDeleted} />
    </main>
  );
}
