# V0-S01 本地基础设施资源基线

本文件记录本机实测，不用容器配置替代实际结果。

## 运行配置

- 测试日期：2026-09-08
- 主机：Apple Silicon（arm64），macOS 26.5.1
- Docker Desktop：12 CPU、7.65 GiB 可用内存
- 数据配置：tiny（后续 `dev` 与 `scale` 在 V0-S03 交付）
- 镜像与配置：以 `compose.yaml` 和本次 Git 提交为准

## 实测结果

| 项目 | 结果 |
| --- | --- |
| 保留命名卷的全服务启动至全部 healthy | 22 秒 |
| 容器总内存 | 约 1.38 GiB |
| 控制库 | 18.75 MiB |
| 业务库 | 18.04 MiB |
| Redis | 12.89 MiB |
| OpenSearch | 892.2 MiB |
| Milvus / etcd / MinIO | 356.4 / 34.06 / 79.61 MiB |

以上内存是服务刚进入 healthy 后的单次 `docker stats --no-stream` 快照，不代表压力峰值。首次拉取镜像受网络速度影响，未计入启动耗时。运行 `./scripts/infra-status.sh` 可重新获取容器状态和瞬时资源；完整命令与故障演练见 `plan/evidence/V0-S01.md`。

## 开发机降载方式

OpenSearch 固定 512 MB Java heap。日常开发用 tiny 数据，按当前任务只启动必要服务，例如：

```bash
docker compose up -d control-postgres business-postgres redis
```

V0-S01 和阶段验收仍要启动全部服务；不能把部分启动记录为完整基础设施通过。
