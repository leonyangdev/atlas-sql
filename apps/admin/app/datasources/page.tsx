/**
 * 数据源列表页
 *
 * 服务端渲染：列出已登记的数据源，点击进入详情。
 * 加载失败时显示错误卡片而不是崩溃整个页面。
 */

import Link from "next/link";
import { listDatasources } from "../../lib/api";
import type { DataSource } from "../../lib/api";
import { dsStatusLabel, formatDate } from "../../lib/utils";

async function DatasourceList() {
  let datasources: DataSource[] = [];
  let error: string | null = null;

  try {
    datasources = await listDatasources();
  } catch (e) {
    error = e instanceof Error ? e.message : "未知错误";
  }

  if (error) {
    return (
      <div className="card error-card" role="alert">
        <strong>无法加载数据源</strong>
        <p>{error}</p>
        <p className="hint">请确认后端 API（http://127.0.0.1:8000）已启动。</p>
      </div>
    );
  }

  if (datasources.length === 0) {
    return (
      <div className="card empty-card" role="status">
        <strong>暂无数据源</strong>
        <p>请通过 API 或管理工具登记第一个数据源。</p>
        <pre className="code-hint">
          {`POST /api/v1/datasources
x-admin-token: <ATLAS_ADMIN_TOKEN>
{
  "slug": "nova-retail",
  "name": "NovaRetail 业务库",
  "kind": "postgresql",
  "host": "127.0.0.1",
  "port": 5433,
  "database_name": "nova_retail",
  "credential_ref": "env:ATLAS_BUSINESS_OWNER_DATABASE_URL"
}`}
        </pre>
      </div>
    );
  }

  return (
    <table className="data-table" aria-label="数据源列表">
      <thead>
        <tr>
          <th>标识</th>
          <th>名称</th>
          <th>类型</th>
          <th>数据库</th>
          <th>状态</th>
          <th>更新时间</th>
          <th aria-label="操作" />
        </tr>
      </thead>
      <tbody>
        {datasources.map((ds) => (
          <tr key={ds.id}>
            <td>
              <code>{ds.slug}</code>
            </td>
            <td>{ds.name}</td>
            <td>{ds.kind.toUpperCase()}</td>
            <td>
              {ds.host}:{ds.port}/{ds.database_name}
            </td>
            <td>
              <span className={`badge badge-${ds.status}`}>{dsStatusLabel(ds.status)}</span>
            </td>
            <td>{formatDate(ds.updated_at)}</td>
            <td>
              <Link href={`/datasources/${ds.slug}`} className="link-btn">
                详情
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DatasourcesPage() {
  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/">← 控制台</Link>
        </p>
        <h1>数据源管理</h1>
        <p>已登记的数据库连接。通过 API 登记后，触发同步采集表和列的元数据。</p>
      </header>
      <DatasourceList />
    </main>
  );
}
