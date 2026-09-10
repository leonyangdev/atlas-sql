import Link from "next/link";
import NewDatasourceForm from "./new-datasource-form";

export default function NewDatasourcePage() {
  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/datasources">← 数据源列表</Link>
        </p>
        <h1>登记数据源</h1>
        <p>将业务数据库注册到 AtlasSQL，登记后触发同步即可采集表和列的元数据。</p>
      </header>
      <NewDatasourceForm />
    </main>
  );
}
