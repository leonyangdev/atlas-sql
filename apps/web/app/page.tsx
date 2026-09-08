export default function DataAnalystHome() {
  return (
    <main>
      <p className="eyebrow">ATLASSQL / DATA ANALYST</p>
      <h1>企业数据问答工作台</h1>
      <p className="lead">
        V0 先建立可复现的数据基础。自然语言问数、SQL 解释与图表将在后续阶段逐步接入。
      </p>
      <section aria-labelledby="current-stage">
        <h2 id="current-stage">当前阶段</h2>
        <dl>
          <div><dt>版本</dt><dd>V0 · Enterprise Data Foundation</dd></div>
          <div><dt>状态</dt><dd>工程基础建设中</dd></div>
          <div><dt>API</dt><dd><code>GET /health/live</code></dd></div>
        </dl>
      </section>
    </main>
  );
}

