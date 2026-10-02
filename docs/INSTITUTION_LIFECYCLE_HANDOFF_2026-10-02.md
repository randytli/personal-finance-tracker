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
| D1–D4 | 见 git log | 按 owner 决定实现：Production 迁移只读闸门、Pending 排除出所有同步路径、退役 PATCH、Rejected 必须先 retry-onboarding |

### 关键实现

- **状态模型**：`status` 是唯一会被写入的字段；`sync_enabled = status = 'active'`（D2），`published = status IN (active, deactivated)`，两者都是 PostgreSQL STORED 生成列。同步（定时、catch-up、手动）看 `sync_enabled`，账本和分类输入看 `published`；Pending 的摄取只走显式 onboarding（`INGESTION_STATUSES`）。原计划是“可写布尔列 + CHECK”，但现有测试和旧镜像都只写 `status`，会大面积违反约束，所以改为生成列。设计文档 §2 已说明。
- **规则**：Deactivated 继续计入 analytics 和分类，定时同步跳过它，cursor 和 token 原样保留。Pending 不进入已发布分类的输入。
- **激活和停用**：预览在一个最终会回滚的事务里**执行真实的转换代码**，比较转换前后的全账本快照（每笔交易的有效分类和类别，加上每月的 `summarize_monthly_transactions`），并返回 digest。真正执行时，在同一把派生锁下重新计算；digest（包含转换类型）不一致就返回 409 并回滚，所以预览和实际执行由构造保证一致。三个显式操作各自只接受一种源状态：activate 只接受 pending，reactivate 只接受 deactivated，deactivate 只接受 active。reject（pending → disabled）和 retry-onboarding（disabled → pending）在派生锁下执行，并断言账本不变。通用的 `PATCH /status` 已退役，返回 410（D3）。
- **迁移闸门（D1）**：`init_db` 第一步就是只读 preflight。Production 下，迁移应用前只要有非 active 的 Item 就停止，不做任何 DDL；独立命令 `python -m api.lifecycle_preflight` 做同样的只读检查，阻止时退出码为 2。
- **Checks**：已实现 K1、K2、K3（含 K4）、K5、K6、K7、K8、K10、K12。fail 级别的检查会阻止预览和激活。

## 验证（全部只在临时集群和合成数据上）

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

## 待决（需要你拍板）

已决定并实现（2026-10-02）：D1 强制只读迁移闸门；D2 Pending 排除出定时、catch-up 和手动同步；D3 退役 PATCH，fail closed（410）；D4 Rejected 必须先 retry-onboarding 回到 Pending。

设计问题（详见设计文档 §10）：
- **D5** 重新激活时 cursor 失效，是否允许受控重置。默认否。
- **D6** Deactivated 的机构能否继续导入账单。默认否。
- **D7** 页面是否提供 Pending 的拉取/规范化按钮（会调用 Plaid）。默认不提供。
- **D8** 停用是否调用 Plaid `/item/remove`。默认否，代价是可能继续计费。
- **D9** K9 疑似重复检查的规则（目前未实现）。
- **R-1..R-6** Remove institution data（设计文档 §7）：要不要先调用 Plaid `/item/remove`；override 是归档还是删除；账单导入行怎么处理；删除后能否重新 Link；软删除还是硬删除；备份里的残留数据。

实现时新发现的问题：
- **D10** 迁移会给 `items` 表加生成列，导致重写整表，并短暂持有 ACCESS EXCLUSIVE 锁（表很小）。Production 执行需要你批准，并选在没有同步运行的时间窗。
- **D11** 回滚兼容性：迁移后旧镜像仍能工作，但旧镜像不认识 `deactivated`（会把它当作被排除），而且旧镜像的 PATCH 不经预览就能激活。建议 Production 迁移后，在停用任何 Item 之前，先确认新镜像已经上线。
- **D12** 预览和激活各自都会做两次全账本快照和一次全量重分类，并持有派生锁。Production 规模下的耗时还没测（参见 M5 R13：分类是 O(n²) CPU）。
- **D13** 旧的 `GET /items/{id}/classification-preview` 还保留着，是否删除？
- **D14** App 里还没有通往 `/plaid/items/<id>` 的入口（没有机构列表页），只能直接输入 URL。是否从 Overview 或同步状态区链接过去？
- **D15** 迁移彩排的合成库里没有账单导入行（statement import），这是覆盖缺口。
- **D16** 逐 Item 的直连端点（`POST /plaid/accounts`、`/plaid/transactions`、`/plaid/transactions/normalize`）对 **Active** Item 仍然可用（现有测试和工具依赖这一点），而它们绕过了 `sync_all` 的原子流程。是否也限制为只用于 Pending onboarding？
- **D17** 页面上没有 reject / retry-onboarding 按钮（只能通过 API），Rejected 页面只显示提示。是否需要按钮，是否需要确认弹窗？

## 下一步（都需要你批准）

1. 审阅三个 commit：`git -C /home/randyli/code/pft-institution-lifecycle log --stat 47183eb..HEAD`。
2. 决定是否合并到 `main`（合并和 push 由你执行）。
3. Production 迁移和发布：按照 D10、D11 另写 action packet，逐条命令批准；第一步是在 Production 上只读运行 `python -m api.lifecycle_preflight`（需要你批准）。
