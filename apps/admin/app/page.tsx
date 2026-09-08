import Link from "next/link";

const modules = [
  {
    href: "/datasources",
    label: "数据源",
    desc: "登记、测试和管理被分析的数据库连接",
    ready: true,
  },
  {
    href: "/metadata",
    label: "元数据",
    desc: "查看采集到的表、列结构，补充业务注释",
    ready: true,
  },
  {
    href: "/metadata?domain=sales",
    label: "业务域",
    desc: "按业务域（Sales / Product / Customer 等）浏览表目录",
    ready: true,
  },
  {
    href: "/datasources",
    label: "同步任务",
    desc: "查看元数据同步历史和失败任务",
    ready: true,
  },
];

export default function AdminHome() {
  return (
    <main>
      <header>
        <p className="eyebrow">ATLASSQL / ADMIN CONSOLE</p>
        <h1>数据治理控制台</h1>
        <p>V0 阶段管理界面。管理数据源登记、元数据采集与同步状态。</p>
      </header>
      <section aria-label="V0 管理模块">
        {modules.map((m) => (
          <article key={m.label}>
            <span>{m.ready ? "V0" : "待开发"}</span>
            <h2>
              {m.ready ? (
                <Link href={m.href} style={{ color: "inherit", textDecoration: "none" }}>
                  {m.label} →
                </Link>
              ) : (
                m.label
              )}
            </h2>
            <p>{m.desc}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
