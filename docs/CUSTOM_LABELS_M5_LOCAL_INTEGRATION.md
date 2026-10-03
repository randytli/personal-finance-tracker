# Custom labels × M5 本地集成验收

**结论：下列固定 SHA 的本地组合可合并。** 先前报告列出的标签/M5
恢复指纹与 fixture 阻塞已解决；本结论不是部署授权，也不代表 M5 所有云端
验收或其他架构门槛已完成。双方原工作树未由本任务修改，未合并 main。

## 固定版本与提交

| 内容 | SHA / 位置 |
| --- | --- |
| Custom labels 输入 | `e63c58e22da9526e7ab8eb53b59e80a85062a095`（含 cd94deb/e63c58e 核对报告） |
| M5 输入 | `97c8ba33fb9e790dabcd16226879907e249069cb`（当前读取到的最新提交） |
| 候选合并提交 | `cdde6fe403782eecb1aea1e5cfff07c9fd132052`，无冲突 |
| 本地适配提交 | `c53d27c`，6 个源码/测试文件；由本任务负责 |
| 候选分支/worktree | `integration/custom-labels-m5` / `~/code/pft-labels-m5-candidate` |

M5 已获通知本轮适配文件及责任范围；不会要求其同时修改原工作树。
候选创建时双方 HEAD 固定为上述 SHA。验收结束后观察到 M5 并行前进到
`e72fc64`（5476de6 / 70b473c / e72fc64：Auth 原型、owner 待办及 Cron 观测
证据工具）。只读 diff 确认这些增量不改本轮 6 个适配文件；它们没有纳入
本候选的组合测试或可合并结论。双方原工作树的这些变化均来自 M5 自己。
后续提交须另做相关差异核对，不能把固定输入的通过结果说成最新 HEAD 已验收。

## 最小适配

- `fingerprint.sql` 动态指纹增加用户函数的身份参数与完整定义 SHA-256
  （含函数级 search_path 等配置），以及非 internal trigger 的定义 SHA-256
  和 `tgenabled`。修改或缺失会改变/移除对象行。同步更新 runner SHA256SUMS。
- Backup fixture 有 Tech 和 Old gear 两个 custom 定义，Tech 的多个关联、
  同一交易多标签，以及归档仍有效的历史和 cleared 审计行。历史先建关联、
  后归档，没有绕过 guard 或删除审计。
- Cron fixture 在私有 schema 显式执行共享 LABEL_SCHEMA_SQL，补 CHINA /
  MEMBERSHIP 种子和 3 functions / 4 guards。函数捕获
  `<fixture schema>, pg_catalog` search_path；PUBLIC 无 schema/function 权限，
  Jobs 获取必要权限，fixture 控制表仍不可被 Jobs 修改。
- 模型表数是 **15**；完整 init_db 还创建旧有 `consumer_scope_migrations`
  标记表，所以 public 完整备份是 **16**。断言明确包括标记表并核对表名集合，
  没有机械修改所有固定数字。Cron 是模型表加自己的 4 张控制/nonce 表。

没有新增财务 schema、分类规则、Auth 功能或金额计算变更。

## 只补相关验证

使用本任务 PostgreSQL 16 合成集群 `127.0.0.1:55449`。真实 Plaid client 和
Python 外网 socket 被禁止；备份存储使用 LocalDirectoryStore，无 GitHub 上传。
本地 age v1.3.2 从官方发布下载到 /tmp 并验证官方 asset digest，未装入应用。

**10 个不同的相关测试最终均有通过结果，0 个未解决失败。** 不是重新运行
完整 Python/UI 验收，也不是声称 10 项在同一次执行通过：首次 9 项中 7 项
通过；只重验两个修正项，再补“恢复后的私有 schema tick”和无 PFT 代码恢复
路径。新增历史 raw fixture 缺字段的失败也仅修正 fixture 后单独重验。

| 验收 | 证据/结果 |
| --- | --- |
| 函数/trigger 指纹负例 | search_path、函数体、trigger 定义、禁用、缺失、DROP FUNCTION CASCADE 共 6 个 subcases 全通过；每次恢复原 guard 后指纹一致 |
| Age backup → emergency key → restore | 标签定义、全部表数据/audit 指纹一致；月度和 membership 汇总一致，包含 3 functions / 4 guards |
| 无 PFT 代码恢复 runbook | age、pg_restore、psql 恢复后扩展指纹一致 |
| Snapshot 一致性 | dump 期间提交的修改不混入源 snapshot 指纹或 dump |
| 恢复后 API 启动 | 真正 FastAPI lifespan、数据库身份检查、runtime schema 和 ready 通过；只读 LOGIN 角色能 SELECT 新表，不能修改定义 |
| 恢复后 writer 约束 | 合法 owner include 成功；跨 owner / archived include SQL 被拒；archive restore 清除后不能再激活关联 |
| 恢复后 Cron 启动与 tick | 私有 schema dump/restore 后指纹一致、ACL 保留；受限 Jobs 权限角色的临时 LOGIN 成员成功执行 tick，新增 2 条合成交易；2 个历史自定义关联和 archive 状态保留 |
| Jobs 权限边界 | 私有 schema 可读写应用表与 guard 执行；禁止更新 fixture_plan，错误 owner 修改被拒绝 |
| 包与 checksum | runner SHA256SUMS、backup staging 和 Cron 单入口 bundle 通过 |

[完整汇总与源码 hash](evidence/custom-labels-m5-local/acceptance.json)。
首次执行的 7 项通过来自已记录工具输出，首次 raw log 被后续定向执行覆盖；
汇总明确注明这一点。后续逐项记录保留：
[表数/角色修正](evidence/custom-labels-m5-local/repaired-count-and-tick.txt)、
[无代码恢复及历史 fixture 首次结果](evidence/custom-labels-m5-local/restored-tick-attempt.txt)、
[最终恢复后 tick](evidence/custom-labels-m5-local/tests.txt)。
所有相关测试 ID 与每次执行结果均在 JSON 中，不把中间失败隐藏为跳过。

原先有效的标签迁移、跨用户、并发、系统规则、82 项 skip 审计、前端和
手机/桌面 QA 沿用既有报告，本轮未重复跑或修改 UI。

## 合并与运行边界

- 可将这个固定版本的候选（包括适配提交）交付合并 review；不能只合并旧
  labels 输入而遗漏 c53d27c，也不能把结论外推到未验收的 M5 新提交。
- 新 runner 的 function/trigger 指纹格式用于新备份点。历史备份恢复应使用
  其记录的 runner 版本/匹配指纹格式；不能以忽略差异方式消除约束验收。
- 本地 role/ACL 验收不是 Supabase/Vercel 云端权限验收。M5 恢复工具使用
  --no-privileges，真实目标需由 owner 显式恢复角色授权；本次 public 恢复测试
  按此过程重建 reader/writer 权限，Cron 私有恢复另验证保留 ACL 的路径。
- 后端仍须先显式 `python -m api.migrate_once`，再更新 API/jobs，后更新 web，
  最后恢复写入；新备份工具也须同步更新校验文件。服务启动不自动迁移。
- 无 down migration。旧标签枚举 CHECK 与 custom audit 不兼容；不可删除定义
  或 guards 作为回滚。优先保留迁移后数据修复前进；若恢复旧备份，须另行授权
  并处理备份后增量。详细顺序沿用 CUSTOM_LABELS_MERGE_REVIEW.md。

本轮未部署、推送、调用 Plaid、访问或修改 Production、创建/变更云端资源。
结束后已停止本任务专用数据库；保留候选 worktree、提交和合成证据供 review。
