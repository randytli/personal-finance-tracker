# 交接：Institution lifecycle（任务 6）— 2026-10-02

分支：`feature/institution-lifecycle`，从 `main` @ `47183eb` 创建，与 `m5-remaining-20261002` 互不依赖。worktree：`/home/randyli/code/pft-institution-lifecycle`。**未 push，未合并，未改动 `main`。**

本节单独成文，没有写进 `docs/M5_OVERNIGHT_HANDOFF_2026-10-02.md`。原因：那份文档在 `m5-remaining-20261002` 分支上，白天有其他会话还在往那个 worktree 提交，同时编辑可能互相覆盖。需要合并时，把本文作为一节贴过去即可。

## 时间

- 开始：01:14 EDT（`date` 实测）。6a、6b 在 01:31 前完成并提交。
- 6c 开发中途会话中断。用户发来“继续完成”后，13:19 EDT 恢复，这时已经过了 03:00 的截止时间。按这条新指令继续完成 6c，硬性边界不变。13:25 提交 6c。

## 做到哪个阶段：6a、6b、6c 全部完成

| 阶段 | commit | 内容 |
|---|---|---|
| 6a 设计 | `5e273e7` | `docs/PFT_INSTITUTION_LIFECYCLE_DESIGN_2026-10-02.md`：盘点及三类范围归类表、状态模型、关键规则、激活影响预览、pre-activation checks、与锁/cursor 的关系、Remove institution data（只写设计） |
| 6b 后端 | `a889826` | 迁移、生命周期服务、API、测试、迁移彩排脚本和证据；设计文档 §2 按实现修订，并新增 §11 验证结果 |
| 6c 前端 | `f59dca1` | `/plaid/items/<item_id>` 页面、确认弹窗、Jest 测试、浏览器 QA 脚本 |
| 文档 | `a591ce2` | runbook 激活步骤改为“预览 + 确认”；本交接文档 |
| D1–D4 | `b9a372b` `797363f` `4af3b39` | 按 owner 决定实现：Production 迁移只读闸门、Pending 排除出所有同步路径、退役 PATCH、Rejected 必须先 retry-onboarding |
| D16 | `76b234e` | 拆分式导入和 normalize 只用于 Pending onboarding；Active 只保留带锁的账户元数据 maintenance |
| D17 | `c4acb49` | Cancel onboarding / Retry onboarding UI，二次确认 |

### 关键实现

- **状态模型**：`status` 是唯一会被写入的字段；`sync_enabled = status = 'active'`（D2），`published = status IN (active, deactivated)`，两者都是 PostgreSQL STORED 生成列。同步（定时、catch-up、手动）看 `sync_enabled`，账本和分类输入看 `published`；Pending 的摄取只走显式 onboarding（`INGESTION_STATUSES`）。原计划是“可写布尔列 + CHECK”，但现有测试和旧镜像都只写 `status`，会大面积违反约束，所以改为生成列。设计文档 §2 已说明。
- **规则**：Deactivated 继续计入 analytics 和分类，定时同步跳过它，cursor 和 token 原样保留。Pending 不进入已发布分类的输入。
- **激活和停用**：预览在一个最终会回滚的事务里**执行真实的转换代码**，比较转换前后的全账本快照（每笔交易的有效分类和类别，加上每月的 `summarize_monthly_transactions`），并返回 digest。真正执行时，在同一把派生锁下重新计算；digest（包含转换类型）不一致就返回 409 并回滚，所以预览和实际执行由构造保证一致。三个显式操作各自只接受一种源状态：activate 只接受 pending，reactivate 只接受 deactivated，deactivate 只接受 active。reject（pending → disabled）和 retry-onboarding（disabled → pending）在派生锁下执行，并断言账本不变。通用的 `PATCH /status` 已退役，返回 410（D3）。
- **迁移闸门（D1）**：`init_db` 第一步就是只读 preflight。Production 下，迁移应用前只要有非 active 的 Item 就停止，不做任何 DDL；独立命令 `python -m api.lifecycle_preflight` 做同样的只读检查，阻止时退出码为 2。
- **Checks**：已实现 K1、K2、K3（含 K4）、K5、K6、K7、K8、K10、K12。fail 级别的检查会阻止预览和激活。

## 验证（全部只在临时集群和合成数据上）

- **D16、D17 之后（最终）**：Python 全套 321 个测试 OK（lifecycle 测试 17 项）；Jest 13 个 suite、70 个测试 OK；`tsc`、`npm run build` 通过；三种宽度的浏览器 QA（新增取消接入 → 重新接入流程）通过。
- **D1–D4 之后**：Python 全套 318 个测试 OK（lifecycle 测试从 9 项增加到 14 项，覆盖 D1–D4，并做了变异检查）；Jest 69 个测试、tsc、build、三种宽度的浏览器 QA（新增重新激活流程）全部通过。彩排库：严格 preflight 退出码 2，Production 下 `init_db` 在 DDL 前停止，库不变；旧代码与新代码指纹仍然一致。
- Python（D1–D4 之前）：全套 313 个测试 OK（含所有 DB opt-in，以及新增的 `PFT_LIFECYCLE_SYNTHETIC_TEST`）；compileall、`git diff --check` 通过。
- 迁移彩排：用 `main` 代码建库、灌数、分类，再用本分支代码迁移两次。迁移前后（以及各自重新分类后）四份指纹完全一致：transactions/raw md5、Item cursor/token 摘要、分类哈希、analytics 哈希（284 行、6 个月）。证据在 `docs/evidence/institution-lifecycle-2026-10-02/`。
- 同一个库上的 Ally 激活预览：6 笔 Chase Zelle 收入变成内部转账，每月 income −75。预览不改变数据库。
- 你要求的 5 个场景都有测试：跨机构配对时预览 = 实际；停用后 analytics 和分类不变；停用后定时同步跳过；重新激活从原 cursor 继续；中途失败整体回滚。另外还测了：预览过期被拒、checks 阻止激活、Pending 隔离、迁移后指纹一致。变异检查：把 `published` 改成只看 active 时，2 项测试失败。
- 前端：Jest 13 个 suite、67 个测试通过；`tsc --noEmit` 通过；`npm run build` 通过（新路由 `ƒ /plaid/items/[item_id]`）。
- 浏览器 QA（`scripts/pft_lifecycle_browser_qa.cjs`）：Chromium 下 360×740、768×1024、1366×900 三个尺寸。用本地 `next start`（127.0.0.1:3007），所有 API 由 Playwright 拦截并返回合成数据，跨域请求一律 abort。检查了：无横向滚动；弹窗在视口内，金额不溢出单元格；Tab 焦点留在弹窗内；Esc 关闭弹窗且不写入；打开页面不发 POST；取消不写入；确认只提交一次且带 digest；failed check 时按钮禁用；读取失败显示错误。人工看截图时发现按月汇总的金额互相重叠，已修复，并把这类重叠加进了脚本断言。
  - 局限：headless Chromium 缺系统库，用的是 `/tmp/pft-browser-libs.RIq77i` 里已有的库（`LD_LIBRARY_PATH`）；没有 emoji 字体，类别 emoji 显示成方框（与其他页面一致，属于环境问题）；没有测 WebKit 和真机。

## 边界遵守

- 未访问本机 Production 数据库，未对 api/jobs/web/db 容器执行任何 docker 命令。127.0.0.1:5432 上有监听，没有连接它。
- 未碰 Supabase、Vercel，未调用 Plaid（测试全部用 fake client，页面不提供拉取按钮）。
- 未读取 `/tmp/pft-m5-cloud-private-20261001/`、`.env*` 或任何凭据文件。Python 解释器借用主 checkout 的 `.venv/bin/python`，node 依赖借用主 checkout 的 `node_modules`（只读，通过软链接 `node_modules`；删除软链接被 deny 规则拦下，所以它还在，已被 gitignore；`.next` 构建产物也还在）。
- 临时 PG16 集群在 job scratch 目录（127.0.0.1:55439，trust 认证），用完已停止并删除。
- 只在 `feature/institution-lifecycle` 上 commit，未 push。

## 已决定并实现

- D1 强制只读迁移闸门；D2 Pending 排除出定时、catch-up 和手动同步；D3 退役 PATCH，fail closed（410）；D4 Rejected 必须先 retry-onboarding。
- D16 `/plaid/transactions`、`/plaid/transactions/normalize`、`/plaid/accounts` 只接受 Pending；摄取服务必须显式传入状态范围；Active 只保留 `POST /plaid/items/{id}/maintenance/account-metadata`（只限 Active、派生锁、账户集合或类型有变化就拒绝、不导入、不动 cursor）。
- D17 Cancel onboarding / Retry onboarding，二次确认；retry 只改状态。

## 剩余待决：merge blocker 与 Production gate 的区分

### Merge blocker

代码层面**没有**未解决的 merge blocker：全部测试通过，D1–D4、D16、D17 都已实现。

有一个需要你在 merge 前**确认**的耦合（不是缺陷）：
- **M-1** merge 后，`main` 上的 API、jobs 和备份/恢复检查（`verify_runtime_schema`）在 lifecycle 迁移完成之前**拒绝启动**。所以 merge 之后，从 `main` 发出的任何 api/jobs 部署都必须带上这次迁移窗口。如果近期不打算做迁移，建议先不 merge，或者 merge 后暂停从 `main` 部署 api/jobs。M5 分支 rebase 到新的 `main` 时也会继承这个要求（例如备份恢复演练需要先迁移）。

### Production deployment / migration gate（merge 不受影响，发布前必须处理）

| 项 | 内容 | 什么时候必须解决 |
|---|---|---|
| D1 闸门的执行 | 已实现；在 Production 上只读运行 `python -m api.lifecycle_preflight` 需要你批准，退出码必须为 0 | 迁移前 |
| D10 | 迁移会给 `items` 加生成列，重写整表并短暂持有 ACCESS EXCLUSIVE 锁：选在没有同步运行的时间窗，逐条命令批准 | 迁移时 |
| D11 | 回滚兼容性：旧镜像不认识 `deactivated`，且旧镜像的 PATCH 可以不经预览就激活。api/jobs/web 要一起换成新镜像；在新镜像确认上线之前，不要停用任何 Item；回滚 packet 要写清楚这两点 | 部署时 |
| D15 | 迁移彩排的合成库里没有账单导入行。建议在临时集群上用 Production 备份的恢复副本再彩排一次（需要你批准使用备份） | 迁移前 |
| D12 | 预览和激活在 Production 规模下的耗时未测（要持有派生锁，并跑两次快照和一次全量分类）。在恢复副本上测一次 | 第一次在 Production 预览或激活之前（不影响迁移本身） |

### 两者都不是（后续功能或策略，可在 merge 和发布之后再定）

- **D5** 重新激活时 cursor 失效，是否允许受控重置（默认否：走 blocked 路径，等你处理）。
- **D6** Deactivated 的机构能否导入账单（默认否）。
- **D7** 页面上是否提供 Pending 的拉取/规范化按钮（会调用 Plaid；默认不提供，走 runbook）。
- **D8** 停用时是否调用 Plaid `/item/remove`（默认否；代价是可能继续计费）。**第一次在 Production 停用之前**应当定下来。
- **D9** K9 疑似重复检查（目前未实现，只会是 warn 级别）。
- **D13** 旧的只读 `GET /items/{id}/classification-preview` 是否删除（无害，已被全账本预览取代）。
- **D14** App 里还没有通往 `/plaid/items/<id>` 的入口（需要直接输入 URL）。
- **R-1..R-6** Remove institution data（设计文档 §7，未实现）：是否先调用 `/item/remove`、override 是归档还是删除、账单导入行、删除后能否重新 Link、软删除还是硬删除、备份里的残留。这些只阻塞“删除机构数据”功能本身的实现。

## 下一步（都需要你批准）

1. 审阅全部 commit：`git -C /home/randyli/code/pft-institution-lifecycle log --stat 47183eb..HEAD`。
2. 确认 M-1 之后，再决定是否合并到 `main`（合并和 push 由你执行）。
3. Production 迁移和发布：按照 D10、D11 另写 action packet，逐条命令批准；第一步是在 Production 上只读运行 `python -m api.lifecycle_preflight`（需要你批准）。
