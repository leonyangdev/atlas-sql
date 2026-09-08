/**
 * 数据源详情页
 *
 * 展示数据源基本信息 + 最近同步任务列表。
 * 同步触发通过 SyncTrigger 客户端组件发送 API 请求。
 */

import Link from "next/link";
import { getDatasource, listSyncJobs } from "../../../lib/api";
import type { DataSource, SyncJob } from "../../../lib/api";
import { dsStatusLabel, formatDate, syncStatusLabel } from "../../../lib/utils";
import SyncTrigger from "./sync-trigger";

interface Props {
  params: Promise<{ slug: string }>;
}

async function DatasourceDetail({ slug }: { slug: string }) {
  let ds: DataSource;
  let jobs: SyncJob[] = [];
  let error: string | null = null;

  try {
    ds = await getDatasource(slug);
    jobs = await listSyncJobs(slug);
  } catch (e) {
    error = e instanceof Error ? e.message : "未知错误";
    return (
      <div className="card error-card" role="alert">
        <strong>加载失败</strong>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <>
      {/* 基本信息 */}
      <section className="detail-section">
        <h2>基本信息</h2>
        <dl className="info-grid">
          <dt>标识 (slug)</dt>
          <dd>
            <code>{ds.slug}</code>
          </dd>
          <dt>名称</dt>
          <dd>{ds.name}</dd>
          <dt>类型</dt>
          <dd>{ds.kind.toUpperCase()}</dd>
          <dt>主机 / 端口</dt>
          <dd>
            {ds.host}:{ds.port}
          </dd>
          <dt>数据库</dt>
          <dd>{ds.database_name}</dd>
          <dt>凭据引用</dt>
          <dd>
            <code>{ds.credential_ref}</code>
          </dd>
          <dt>状态</dt>
          <dd>
            <span className={`badge badge-${ds.status}`}>{dsStatusLabel(ds.status)}</span>
          </dd>
          <dt>描述</dt>
          <dd>{ds.description ?? "—"}</dd>
          <dt>创建时间</dt>
          <dd>{formatDate(ds.created_at)}</dd>
        </dl>
        {/* 客户端同步触发按钮 */}
        <SyncTrigger slug={ds.slug} />
      </section>

      {/* 同步任务历史 */}
      <section className="detail-section">
        <h2>同步任务（最近 20 次）</h2>
        {jobs.length === 0 ? (
          <p className="empty-hint">尚未执行同步任务。点击上方「触发同步」开始采集元数据。</p>
        ) : (
          <table className="data-table" aria-label="同步任务列表">
            <thead>
              <tr>
                <th>ID</th>
                <th>状态</th>
                <th>表数</th>
                <th>列数</th>
                <th>重试</th>
                <th>开始时间</th>
                <th>完成时间</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>
                    <span className={`badge badge-sync-${job.status}`}>
                      {syncStatusLabel(job.status)}
                    </span>
                  </td>
                  <td>{job.tables_discovered ?? "—"}</td>
                  <td>{job.columns_discovered ?? "—"}</td>
                  <td>{job.retry_count}</td>
                  <td>{formatDate(job.started_at)}</td>
                  <td>{formatDate(job.finished_at)}</td>
                  <td className="error-cell">{job.error_summary ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* 跳转到元数据浏览 */}
      <section className="detail-section">
        <h2>元数据</h2>
        <p>
          <Link href={`/metadata?datasource_id=${ds.id}`} className="link-btn primary-btn">
            浏览此数据源的表 →
          </Link>
        </p>
      </section>
    </>
  );
}

export default async function DatasourceDetailPage({ params }: Props) {
  const { slug } = await params;

  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/datasources">← 数据源列表</Link>
        </p>
        <h1>{slug}</h1>
        <p>数据源详情与同步任务状态。</p>
      </header>
      <DatasourceDetail slug={slug} />
    </main>
  );
}
