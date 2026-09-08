const modules = ["数据源", "元数据", "业务域", "同步任务"];

export default function AdminHome() {
  return (
    <main>
      <header>
        <p className="eyebrow">ATLASSQL / ADMIN CONSOLE</p>
        <h1>数据治理控制台</h1>
        <p>V0 管理界面骨架。数据源与元数据工作流将在 V0-S04 和 V0-S07 接入。</p>
      </header>
      <section aria-label="V0 管理模块">
        {modules.map((module) => (
          <article key={module}>
            <span>待开发</span>
            <h2>{module}</h2>
            <p>接口和状态以对应用户故事的验收要求为准。</p>
          </article>
        ))}
      </section>
    </main>
  );
}

