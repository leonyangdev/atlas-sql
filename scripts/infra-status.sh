#!/bin/sh
set -eu

# 第一条命令显示 Compose 健康状态；第二条只取一次资源快照，不持续占用终端。
docker compose ps
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
