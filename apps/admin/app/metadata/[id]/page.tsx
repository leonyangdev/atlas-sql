/**
 * 表详情页
 *
 * 展示：
 * - 表级信息（粒度、权威来源、同步状态、人工注释）
 * - 字段列表（数据类型、是否主键/外键、敏感等级、样例值）
 *
 * 关键验收：能从界面定位一张表的粒度、字段与同步版本。
 */

import Link from "next/link";
import { getTable } from "../../../lib/api";
import type { ColumnMeta, TableMeta } from "../../../lib/api";
import { parseSampleValues } from "../../../lib/utils";

interface Props {
  params: Promise<{ id: string }>;
}

function ColumnRow({ col }: { col: ColumnMeta }) {
  const samples = parseSampleValues(col.sample_values);

  return (
    <tr className={col.is_deleted ? "row-deleted" : ""}>
      <td>
        <code>{col.column_name}</code>
        {col.is_primary_key && <span className="badge badge-pk" title="主键">PK</span>}
      </td>
      <td>{col.manual_business_name ?? <span className="empty-hint">—</span>}</td>
      <td>
        <code>{col.data_type}</code>
      </td>
      <td>{col.is_nullable ? "是" : "否"}</td>
      <td>
        {col.foreign_key_ref ? (
          <code className="fk-ref" title={col.foreign_key_ref}>
            {col.foreign_key_ref.split(".").slice(-2).join(".")}
          </code>
        ) : (
          "—"
        )}
      </td>
      <td>
        {col.manual_sensitivity ? (
          <span className={`badge badge-sens-${col.manual_sensitivity}`}>
            {col.manual_sensitivity}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td>
        {col.manual_description ?? col.raw_comment ?? <span className="empty-hint">—</span>}
      </td>
      <td>
        {samples.length > 0 ? (
          <span className="sample-values">
            {samples.slice(0, 5).map((v, i) => (
              <code key={i} className="sample-chip">
                {v}
              </code>
            ))}
          </span>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

async function TableDetail({ tableId }: { tableId: number }) {
  let table: TableMeta;
  let error: string | null = null;

  try {
    table = await getTable(tableId);
  } catch (e) {
    error = e instanceof Error ? e.message : "未知错误";
    return (
      <div className="card error-card" role="alert">
        <strong>加载失败</strong>
        <p>{error}</p>
      </div>
    );
  }

  const activeColumns = table.columns.filter((c) => !c.is_deleted);
  const deletedColumns = table.columns.filter((c) => c.is_deleted);

  return (
    <>
      {/* 表级信息 */}
      <section className="detail-section">
        <h2>表信息</h2>
        <dl className="info-grid">
          <dt>物理名称</dt>
          <dd>
            <code>
              {table.schema_name}.{table.table_name}
            </code>
          </dd>
          <dt>业务名称</dt>
          <dd>{table.manual_business_name ?? <span className="empty-hint">未填写</span>}</dd>
          <dt>业务域</dt>
          <dd>
            {table.manual_domain ? (
              <Link href={`/metadata?domain=${table.manual_domain}`} className="domain-tag">
                {table.manual_domain}
              </Link>
            ) : (
              <span className="empty-hint">未填写</span>
            )}
          </dd>
          <dt>表类型</dt>
          <dd>{table.table_type}</dd>
          <dt>行数估算</dt>
          <dd>{table.row_estimate?.toLocaleString() ?? "—"}</dd>
          <dt>粒度（Grain）</dt>
          <dd>
            {table.manual_grain ?? (
              <span className="empty-hint">
                未填写 —{" "}
                <Link
                  href={`/metadata/${table.id}/annotate`}
                  className="link-btn"
                >
                  填写
                </Link>
              </span>
            )}
          </dd>
          <dt>权威来源</dt>
          <dd>{table.manual_authoritative_source ?? <span className="empty-hint">未填写</span>}</dd>
          <dt>描述</dt>
          <dd>
            {table.manual_description ?? table.raw_comment ?? (
              <span className="empty-hint">未填写</span>
            )}
          </dd>
          <dt>别名</dt>
          <dd>
            {table.manual_aliases ? (
              <code>{table.manual_aliases}</code>
            ) : (
              <span className="empty-hint">—</span>
            )}
          </dd>
          <dt>数据源 ID</dt>
          <dd>
            <Link href={`/datasources`} className="link-btn">
              {table.datasource_id}
            </Link>
          </dd>
        </dl>
      </section>

      {/* 列详情 */}
      <section className="detail-section">
        <h2>
          字段列表（{activeColumns.length} 个活跃字段
          {deletedColumns.length > 0 ? `，${deletedColumns.length} 个已删除` : ""}）
        </h2>

        {table.columns.length === 0 ? (
          <p className="empty-hint">暂无字段数据，请先执行元数据同步。</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table column-table" aria-label="字段列表">
              <thead>
                <tr>
                  <th>列名</th>
                  <th>业务名称</th>
                  <th>数据类型</th>
                  <th>可为空</th>
                  <th>外键</th>
                  <th>敏感等级</th>
                  <th>描述</th>
                  <th>样例值</th>
                </tr>
              </thead>
              <tbody>
                {activeColumns.map((col) => (
                  <ColumnRow key={col.id} col={col} />
                ))}
                {deletedColumns.map((col) => (
                  <ColumnRow key={col.id} col={col} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

export default async function TableDetailPage({ params }: Props) {
  const { id } = await params;
  const tableId = Number(id);

  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/metadata">← 元数据列表</Link>
        </p>
        <h1>表详情</h1>
        <p>查看表的粒度、字段结构、敏感等级与采集样例值。</p>
      </header>
      <TableDetail tableId={tableId} />
    </main>
  );
}
