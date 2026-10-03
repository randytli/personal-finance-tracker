# 自定义标签：M5 增量复核与 Windows 独立发布

## 固定输入与结论

- 当前 main：`47183eb73d305a56e209b67c2c4bb06810e9dcfb`，也是标签分支的起点。
- 标签分支：`e63c58e22da9526e7ab8eb53b59e80a85062a095`。
- 此次只读复核 M5：`97c8ba33fb9e790dabcd16226879907e249069cb..e72fc64f3a3367e87b7255e7dbf4cba0c57b0302`。
- 候选合入该固定增量：`8849195d93e1acc107a0055ac927f6b3c8eb2481`。沿用适配提交 `c53d27cb4da0d9a596a5adda677bcdc4bd9f1f69`，不修改双方原 worktree。

**① 标签与上述 M5 代码兼容。** 已接受的固定组合验收仍有效，见 [本地集成报告](CUSTOM_LABELS_M5_LOCAL_INTEGRATION.md)。此次相关 Cron 工具已经进入候选并补验；不意味着 M5 已获 SERVERLESS_GO，候选不得直接合入 main。

**② 标签可独立合入上述当前 main，并按现有 Windows 路径发布。** 最小提交集合只有 `7180352ead5c672720f6aaa7cf7a2ca08b445195`（Add user-owned custom transaction labels）。`cd94deb`、`e63c58e` 仅追加核对证据，不是功能依赖。不需要、也不应带入候选分支的 M5 合并提交、`c53d27c` 或 M5 Auth/Cron 代码。此结论是代码、迁移和备份实现的本地发布就绪判断；本轮没有执行 Windows 主机发布或实际主机恢复。

## 增量判断依据

`git diff --name-status 97c8ba3..e72fc64` 共 10 文件、882 行新增，没有修改现有运行时文件。

| 文件/类别 | 判断与处理 |
| --- | --- |
| `docs/M5_OVERNIGHT_HANDOFF_2026-10-02.md` 与三个 `docs/evidence/m5-2026-10-02/cloud/*.json` | 待决事项和已有证据；没有可执行的标签、迁移或恢复变更。没有重新调用这些证据对应的云服务。 |
| `experiments/m5_cloud/auth_probe.py`、`auth_owner_flow.py`、`tests/test_m5_auth_probe.py` | 独立 Auth 可行性原型与测试。API、scripts、deploy 和 `cron_jobs_app.py` 没有引用新模块；没有修改应用依赖或接入 Auth。本人终端 owner flow 涉及云操作，不在本轮执行。与标签隔离约束和发布无关，不重复其验收。 |
| `experiments/m5_cloud/cron_controller.py` | 新增主动运行的 Cron 负例控制工具，调用现有签名函数；不改变 tick/runtime。属于相关验收工具，因此纳入候选，仅 mock HTTP 验证八种请求构造、重放与篡改 body，确认结果不泄露合成凭据。 |
| `cron_observer.py`、`cron_evidence.py` | 新增 SELECT 观测/证据工具，不改表、角色授权或启动入口；无标签表固定总数假设。纳入候选，mock 数据库连接，验证进度、拒绝错误身份、仅执行声明的 SELECT、连接关闭。 |

没有修改 `api/models.py`、数据库初始化/迁移、备份 runner、Cron fixture/stager/entrypoint 或服务入口。因此无需重跑已接受的迁移、指纹篡改检出、恢复权限、启动与合成 tick 测试，也没有扩大 schema 或财务语义范围。

## 本次新增验证

1. `tests/test_m5_cron_tools.py`：**3 tests passed，0 skipped**。所有 HTTP/数据库连接均 mock，未连接云端。原始日志见 [cron-tools.log](evidence/custom-labels-release-split/cron-tools.log)。
2. 标签独立路径 Windows 备份补验：仅加载原标签 worktree 的代码，不加载 M5；PostgreSQL 16、`127.0.0.1:55449`、独立合成数据库。实际使用未修改的 `api.backup` 与 `api.backup_crypto`，加密为 PFTENC2 后删除未加密 dump/manifest，再仅凭加密包解密并恢复到新数据库。见 [结果](evidence/custom-labels-release-split/windows-backup-results.json) 与 [可复核脚本](evidence/custom-labels-release-split/windows-backup-probe.py)。源和目标合成数据库已清理。

恢复后实际通过：16 张表逐行比较；自定义活动/归档标签、关联及清除后的审计决定保留；3 个 guard 函数定义、4 个触发器定义及启用状态一致；启动 schema 验证通过；数据库拒绝跨用户关联、归档新增和关联后的 owner 改动；归档 restore 清除决定后仍禁止重新 include；月净支出与 membership 汇总不变；源库没有被恢复操作改写。

**当前 Windows 备份实现会自动覆盖新表和 guards。** `api.backup` 使用全库 `pg_dump -Fc`，没有固定表白名单；manifest 的 `schema_sha256` 覆盖规范化的 schema dump，其中含新表、函数与触发器，PFTENC2 包含 dump 和 manifest。本次直接验证了这些对象确实随现有路径恢复。与 M5 的逐对象恢复指纹适配是两件事：Windows 无需引入 `c53d27c` 才能备份/恢复 guards。升级前旧库当然没有新表，必须先迁移后产生新的备份。

限制：本次使用 Linux 本地 PostgreSQL 验证相同 Python/pg_dump 恢复路径，并非 Windows 操作系统或实际主机的演练。`pg_restore --no-owner --no-privileges` 不恢复集群角色或 ACL；跨新集群恢复仍需现有 runbook 的角色/owner 配置，不能把数据备份当角色备份。启动检查 guard 存在和启用状态，完整定义保真由 dump/schema 指纹及本次恢复比较证明。

## 独立发布顺序与回滚

只将 `7180352` 纳入当前 main 的发布候选；正常构建与原有 Windows 服务配置保持一致。发布需先取得迁移前备份并暂停写入，使用新后端代码显式执行 `python -m api.migrate_once`，然后更新/重启 API 与 jobs，确认启动 schema 检查通过，再更新前端并恢复写入。启动不会代替显式迁移。完成升级后产生新备份；上述步骤没有在 Production 执行。

不执行破坏性 down migration：旧系统标签 CHECK 不能容纳已有自定义标签 ID。回退应用版本时保留新增表/guards，不擅自删除历史标签关联；schema 问题优先前向修复。恢复迁移前备份会丢失该时间点以后的数据，必须另行授权和安排停写。M5 仍必须等 SERVERLESS_GO，独立标签发布不带入它的代码。
