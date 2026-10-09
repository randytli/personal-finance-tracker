# Institution lifecycle：Pending / Active / Deactivated 设计

> 2026-10-02 修订：owner 已拍板 D1–D4、D8、D14、D16、D17 和 M-1（见 §10），本文按决定更新。

日期：2026-10-02（无人值守夜间任务 6a）。分支：`feature/institution-lifecycle`，从 `main` @ `47183eb` 创建，与 M5 分支互不依赖。
范围：只写设计。本节不包含任何 Production 操作、Plaid 调用或云端写入。

## 1. 现状盘点

### 1.1 现有的 pending / onboarding 后端

| 环节 | 位置 | 现有行为 |
|---|---|---|
| 新建 Item | `api/routes/plaid.py` `exchange_public_token` | Link 交换后验证机构，写入 `status='pending'`。同一 user 的同一 institution 只能有一个 Item（`uq_items_user_institution`；`_institution_exists` 不看状态）。 |
| 发现账户 | `POST /plaid/accounts?item_id=`，`persist_account_metadata` | 允许 pending/active；按账户类型给出初始 `consumer_transactions_enabled`。 |
| 手动拉取交易 | `POST /plaid/transactions?item_id=`，`persist_consumer_transactions` | 允许 pending/active；**不经过** `sync_all` 原子流程，单独一个事务，推进 `transactions_cursor`。 |
| 规范化 | `POST /plaid/transactions/normalize?item_id=`，`normalize_item_transactions` | 允许 pending/active。 |
| 分类预览 | `GET /plaid/items/{id}/classification-preview`，`preview_pending_classification` | REPEATABLE READ READ ONLY；以 active ∪ {该 pending} 为输入计算，**只返回该 pending Item 自己的交易**，不显示对已有交易的影响。 |
| 激活 | `PATCH /plaid/items/{id}/status {"status":"active"}`，`activate_item` | 取派生锁，`validate_consumer_activation`（至少一个启用账户；账户归属一致；禁用账户上没有新数据），置 active，`classify_active_transactions`。可以从 `disabled` 直接激活。没有预览确认，也不会比对预览。 |
| 拒绝 | 同一端点 `{"status":"disabled"}` | 只允许 pending/disabled → disabled；active 不能停用（409）。现在的 `disabled` 实际含义是“拒绝的 pending”。 |
| 账单导入 | `statement_imports/persistence.py` | 目标 Item 必须是 pending/active；只有 active Item 才写种子分类。 |
| Runbook | `docs/MULTI_INSTITUTION_PRODUCTION.md` | 手动 curl 流程，没有前端页面。 |

### 1.2 所有“看 Item 状态”的地方及归类

三类范围的定义：
- **同步范围**：哪些 Item 会被拉取，或推进 cursor / token 相关状态。
- **账本范围（analytics）**：哪些交易进入已发布的 analytics、review、明细。
- **分类输入范围**：哪些交易参与已发布分类的计算（转账配对、退款匹配、Amex 权益账户集合），并接收分类写入。

| # | 位置 | 现有条件 | 类别 | 新条件 |
|---|---|---|---|---|
| S1 | `api/jobs.py` `request_sync` 选定 Item 校验 | `status='active'` | 同步 | `sync_enabled`（只有 Active 为 true，D2） |
| S2 | `api/jobs.py` `tick` 到期 Item（含启动后 catch-up） | `status='active' AND NOT sync_paused` | 同步 | `sync_enabled AND NOT sync_paused` |
| S3 | `api/services/sync_all.py` `sync_all` 选 Item | 同上 | 同步 | 同上 |
| S4 | `api/services/sync_all.py` `_revalidate` 发布前复核 | `status != 'active'` 即 stale | 同步 | 复核同一谓词；Item 在 fetch 与 publish 之间被停用 → `stale_item`，整 Item 回滚，cursor 不动 |
| S5 | `api/routes/plaid.py` `POST /plaid/transactions`、`/transactions/normalize`、`/accounts` | pending/active | 摄取（只用于 Pending onboarding，D16） | 只接受 `pending`；Active、Deactivated、Rejected 一律 409，且在任何 Plaid 调用之前拒绝。Active 的账户元数据只能走 maintenance 操作（§6） |
| S6 | `api/services/persistence.py` `persist_consumer_transactions`、`persist_account_metadata` | pending/active | 摄取 | 必须显式传入 `statuses`：`sync_all` 传 `ATOMIC_SYNC_STATUSES`（active），onboarding 传 `ONBOARDING_STATUSES`（pending）。没有默认值，所以不存在隐式的旁路 |
| S7 | `api/services/derivation.py` `normalize_item_transactions` | pending/active | 摄取（派生） | 同 S6 |
| S8 | `api/routes/sync.py` `/sync/status` 列表 | 展示 status | 只读展示 | 增加 `sync_enabled`、`published` 字段 |
| L1 | `api/routes/analytics.py` `_active_analytics_rows`（所有 analytics 端点共用） | `status='active'` | 账本 | `published` |
| L2 | `api/routes/review.py` `_transaction_scope`（单笔 review/override） | `status='active'` | 账本 | `published` |
| L3 | `api/routes/review.py` 批量 review（约 397 行） | `status='active'` | 账本 | `published` |
| L4 | `api/routes/review.py` `_review_filters`（review 队列） | `status='active'` | 账本 | `published` |
| L5 | `api/routes/review.py` `_label_transaction_scope`（标签） | active/pending | 账本 | `published OR status='pending'`（保持现状：pending 可打标签，Deactivated 也可） |
| L6 | `statement_imports/persistence.py` 导入目标 | pending/active | 账本写入 | 默认保持 `sync_enabled`（Pending、Active）；Deactivated 是否允许导入列为待决 D6 |
| L7 | `statement_imports/persistence.py` 种子分类 | `status='active'` | 分类输入 | `published` |
| L8 | `statement_imports/persistence.py` payment 候选 | pending/active | 分类输入（仅提示） | `published OR status='pending'` |
| C1 | `api/services/derivation.py` `classify_active_transactions`（锁 + 输入 + 写入） | `status='active'` | 分类输入 | `published` |
| C2 | `_classification_inputs` 的 credit / Amex 权益账户集合 | 随 C1 的 scope | 分类输入 | 随 C1 |
| C3 | `preview_pending_classification` | active ∪ {pending} | 分类输入（预览） | 由 §4 的激活影响预览替代；旧端点保留为兼容 |
| C4 | `activate_item` | pending/active/disabled | 状态转换 | 拆成 activate / reactivate / deactivate / reject / retry-onboarding，见 §6 |
| X1 | `api/routes/plaid.py` `_institution_exists` | 不看状态 | 唯一性 | 不变：Deactivated 的机构不能重新 Link，只能重新激活 |
| X2 | `scripts/pft_m6_fingerprint.py`、`pft_m5_benchmark.py` | 读/写 status | 工具 | 指纹加入新列；benchmark 写入时补齐新列 |

注：`lock_consumer_derivation` 锁住用户的**全部** Item 和 Account，不看状态，不需要改。

## 2. 状态模型

### 2.1 选择（6b 实现时修订）

`status` 是唯一被写入的生命周期字段；`sync_enabled` 和 `published` 是 PostgreSQL 的 **STORED 生成列**，由 `status` 推导，不能直接写：

```sql
sync_enabled BOOLEAN NOT NULL GENERATED ALWAYS AS (status = 'active') STORED
published    BOOLEAN NOT NULL GENERATED ALWAYS AS (status IN ('active','deactivated')) STORED
```

| 状态 | `status` | `sync_enabled` | `published` | 同步 | 账本 | 分类输入 |
|---|---|---|---|---|---|---|
| Pending | `pending` | false | false | 只能通过显式 onboarding 动作摄取（D2） | 否 | 否（只出现在预览里） |
| Active | `active` | true | true | 定时 + 手动 | 是 | 是 |
| Deactivated | `deactivated` | false | true | 否 | 是 | 是 |
| Rejected（旧 `disabled`） | `disabled` | false | false | 否 | 否 | 否 |

理由：
- 每类范围只看一列：同步（定时、catch-up、手动）看 `sync_enabled`，只有 Active 为 true；账本和分类输入都看 `published`。三类查询不会再各自解释 `status`。Pending 的摄取不属于同步范围，只走显式 onboarding 动作，代码里用 `INGESTION_STATUSES` 明确写出。
- 最初的设计是“两个可写布尔列 + CHECK 约束”。实现时发现：现有测试、脚本和旧镜像都只写 `status`（包括 raw SQL 插入），可写列加 CHECK 会让它们全部违反约束。改用生成列后，标志位与 `status` 在数据库层面不可能不一致。
- 回滚安全：旧镜像只写 `status`，生成列照常推导。迁移前不存在 `deactivated`，所以 `published` ⇔ `status='active'`，与旧的过滤条件逐行等价。
- 另加审计列：`activated_at`、`deactivated_at`（TIMESTAMPTZ，可空），以及 `activation_digest`（最近一次激活所确认的预览摘要）。

不选纯枚举（不带标志列）：每个查询都要写 `status IN (...)`，“Deactivated 仍计入账本”这条规则会散落在十几处，漏改一处就会让 analytics 悄悄变化。

### 2.2 迁移（`migrate_institution_lifecycle`，幂等，已实现）

0. **强制只读 preflight（D1）**：`init_db` 的第一步就是 `require_lifecycle_preflight`，在任何 DDL 之前执行。`PLAID_ENV=production` 且迁移尚未应用时，只要有任何 Item 不是 `active`（包括 NULL 或未知状态），就抛出 `LifecyclePreflightBlocked` 并停止，不提升、不改写、不猜。部分应用（只有一部分生命周期列）、未知状态、标志位与 status 不一致，在任何环境下都会阻止。迁移应用之后，之后新接入的 Pending Item 不会再挡住 `init_db` 重跑。独立命令 `python -m api.lifecycle_preflight` 在 REPEATABLE READ READ ONLY 事务里执行同样的检查（总是按 Production 规则），只输出各状态的数量，阻止时退出码为 2。
1. 如果存在四个值之外的 `status`，直接 `RAISE`，不猜。
2. `ck_items_status` 扩展为 `pending/active/deactivated/disabled`；已经扩展过则跳过。
3. `ADD COLUMN IF NOT EXISTS sync_enabled/published ... GENERATED ALWAYS AS (...) STORED`。这一步会重写 `items` 表；表很小（每个机构一行），但会短暂持有 ACCESS EXCLUSIVE 锁，所以应在没有同步运行时执行。
4. `activated_at`、`deactivated_at`、`activation_digest` 可空列。
5. 索引 `ix_items_user_lifecycle (user_id, sync_enabled, published)`。
6. 不改任何交易、分类、cursor、token。

预期 Production 现状：全部 Item 都是 `active` → 迁移后全部为 Active + published。这由第 0 步的 preflight 强制保证（D1）。

旧镜像兼容性（回滚时）：旧代码不知道 `deactivated`，会把 Deactivated 的 Item 排除出 analytics（等同于旧的 disabled）。只要还没有停用过任何 Item，回滚就没有影响。

### 2.3 迁移前后不变量

迁移前后必须**逐字节一致**：
- 每个 Item 的 `transactions_cursor`、`access_token` 摘要、`status`；
- `transactions` 全表（去掉时间戳列）的 md5；
- `external_classifications` 的结果（分类哈希）；
- analytics：对每个有数据的月份调用 `summarize_monthly_transactions`，结果的 JSON 哈希；
- 迁移后立刻跑一次 `classify_active_transactions`，写入集必须为空。

6b 已在临时集群上验证（见 §11）。合成库的形状：Chase（checking + credit + 禁用的投资账户）、Amex（权益账户）、一个带数据的 pending（Ally）、一个 disabled，加上手动分类 override、手动类别 override、已删除行、退款对、信用卡还款对、Zelle 对。账单导入行没有放进合成库，属于缺口。

D2 已决定：Pending 不参与定时同步、启动 catch-up 和普通的 Active 手动同步，所以 `sync_enabled` 直接定义为 `status = 'active'`。

## 3. 关键规则

- **R1 Deactivated 继续计入账本和分类输入。** 停用只关掉同步，`published` 保持 true。停用的事务里**不重新分类**，因为输入集合没有变化。测试要验证停用前后 analytics 哈希、分类哈希都不变，并且 `classify_active_transactions` 的写入集为空。
- **R2 Pending 在激活前不能影响任何已发布的分类。** `published=false` 的 Item 不进入 C1 的输入，所以已发布分类与 Pending 数据无关。Pending 自己的交易行 `transaction_type` 保持 NULL（与现状一致）。预览只在会回滚的事务里计算。
- **R3 Pending 的手动拉取不触发已发布分类的重算。** 现在的手动拉取路径本来就不跑分类，保持不变。
- **R4 Rejected（`disabled`）不进任何范围**，与现状一致。

## 4. 激活影响预览

### 4.1 语义

预览比较的是**全账本**激活前和激活后，不只看新机构自己的交易：
- 新机构的交易会进入账本；
- **已有机构**的交易分类也可能改变。例如跨机构转账配对：Chase 的一笔 +$500 原来是 `income`，与新机构的 −$500 配成内部转账后，变成 `transfer`，`is_internal_transfer=true`，于是从收入里消失。再如 Amex 权益账户集合、退款匹配的变化。

### 4.2 计算方式：用会回滚的事务真跑一遍

预览**不另写一套模拟逻辑**，在一个最终 ROLLBACK 的事务里执行和激活完全相同的代码：
1. `lock_consumer_derivation`，与同步、激活、review 写入串行。
2. 拍 **before** 快照：账本范围（`published`）内每笔交易的有效分类（manual override 优先）、有效类别、金额、月份、机构，加上每个月的 `summarize_monthly_transactions`。
3. 调用 `activate_item_in_session`（真实激活路径：校验 → 改状态 → `classify_active_transactions`）。
4. 拍 **after** 快照（同一函数）。
5. 计算差异和摘要，然后 **ROLLBACK**。

这样“预览 = 实际”是由构造保证的，因为两者跑的是同一段代码、同一份输入。

### 4.3 输出

- `summary_by_month`：每个变化月份的指标差（gross、refunds、reimbursements、card_benefits、net_spending、income、net_savings、unclassified_count），以及按类别的 `category_net_breakdown` 差（before/after/delta）。
- `new_transactions`：新机构进入账本的交易（逐笔：日期、金额、商户、分类、类别）。
- `changed_existing_transactions`：**已有交易**里有效分类或类别变化的，逐笔列出 before/after。manual override 锁住的交易不会变；如果变了，说明有 bug。
- `digest`：对 after 快照加 before 快照做 SHA-256，规范化 JSON。

### 4.4 激活时的一致性

`POST /plaid/items/{id}/activate {"preview_digest": ...}`：
- 在同一把锁里重新计算 before/after，摘要必须等于 `preview_digest`，否则返回 409“预览已过期，请重新预览”，并回滚。
- 摘要一致才提交，并把摘要写入 `activation_digest`。
- 由此可以保证：用户确认的就是实际发生的。如果预览和激活之间有同步、override 等任何变化，激活会被拒绝。

## 5. Pre-activation checks

`GET /plaid/items/{id}/activation-checks` 返回每项的 `pass` / `fail` / `warn` 和说明。`fail` 时禁止激活，`warn` 只提示。

| # | 检查 | 判定 | 级别 |
|---|---|---|---|
| K1 | 状态可激活 | `pending`（对应 activate）或 `deactivated`（对应 reactivate）；`disabled` 判 fail，必须先 retry-onboarding 回到 pending（D4） | fail |
| K2 | 已发现账户 | 至少一个 `consumer_transactions_enabled` 账户 | fail |
| K3 | 账户归属一致 | `validate_consumer_activation` 的归属校验（raw 与 normalized 的 account 一致，账户属于该 Item） | fail |
| K4 | 禁用账户上没有新消费数据 | 同上，与 `legacy_consumer_rows` 比对（实现中与 K3 合并为一项） | fail |
| K5 | 已有初始同步 | `transactions_cursor IS NOT NULL` | fail |
| K6 | 规范化完整 | 启用账户上每条未删除的 raw 都有 normalized 行，且值一致（复用 `_normalized_differs`）；源数据校验通过（`validate_normalization_input`） | fail |
| K7 | 已发布分类是最新的 | 用 `published` 范围重算一次，结果与存储值一致（写入集为空）。否则 before 快照就不是用户当前看到的 analytics | fail |
| K8 | 同步状态健康 | `NOT sync_paused`，`metadata_warning IS NULL`，最近一次 `sync_item_runs`（如果有）不是 blocked | warn |
| K9（未实现） | 交易与已有数据没有冲突 | 新 Item 的 transaction_id 不与其他 Item 重复（主键已经保证，这里显式报告），也没有疑似重复（同金额、同日期，对方账户在另一个 published Item，且双方描述都不像转账）→ 列出条数 | warn |
| K10 | 日期范围 | 报告最早和最晚交易日期；早于已发布账本最早日期 → warn（会改写历史月份） | warn |
| K11 | 影响预览可算 | §4 预览成功，返回摘要（不是单独一项检查：预览本身失败就无法激活） | fail |
| K12 | 没有进行中的同步 | `sync_runtime_state.running_sequence` 为空，或已处理 | warn（激活本身会等锁） |

## 6. 状态转换与 atomic workflow、advisory lock、cursor 的关系

所有转换都在 `lock_consumer_derivation` 下进行（事务级 advisory lock，加上全部 Item 和 Account 的行锁）。它和 `sync_all` 的发布阶段、手动拉取、规范化、review 写入、账单导入用的是同一把锁，所以任何转换都不会和发布交错。

| 转换 | 端点 | 做什么 | cursor |
|---|---|---|---|
| Pending → Active（activate） | `POST /items/{id}/activation-preview`，再 `POST /items/{id}/activate`（带 digest） | 只接受 `pending`。checks → `status='active'`，`activated_at=now()` → `classify_active_transactions` → 校验摘要 → 提交。任何一步失败，整体回滚 | 不动 |
| Active → Deactivated（deactivate） | `/deactivation-preview`，再 `/deactivate`（带 digest） | 只接受 `active`。`status='deactivated'`，`deactivated_at=now()`；分类输入不变，写入集为空 | 不动；token 也不动；不调用 Plaid `/item/remove` |
| Deactivated → Active（reactivate） | `/reactivation-preview`，再 `/reactivate`（带 digest） | 只接受 `deactivated`，checks 与 activate 相同。由于 Deactivated 一直是 published，预览差异通常为空，但仍要求确认 | 不动；下一次定时同步从**已保存的 cursor** 增量拉取，补上停用期间的 added/modified/removed |
| Pending → Rejected（reject） | `POST /items/{id}/reject` | 只接受 `pending`；派生锁下执行；两边都未发布，执行前后断言账本快照不变 | 不动 |
| Rejected → Pending（retry-onboarding） | `POST /items/{id}/retry-onboarding` | 只接受 `disabled`（D4）；同上断言。回到 Pending 后，必须重新通过 onboarding 准备、checks、预览和确认激活 | 不动 |
| 账户元数据维护（只限 Active） | `POST /items/{id}/maintenance/account-metadata` | D16 允许的唯一 Active 逐 Item 操作。派生锁下执行，只刷新已知账户的名称和掩码。账户集合有增减、或账户类型漂移，返回 409 且不写入；不导入、不 normalize、不分类、不动 cursor；执行前后断言财务账本不变（显示名称除外） | 不动 |
| 断开连接（D8，可选） | `/deactivate` 带 `{"disconnect": true}`，或对已停用的 Item 调用 `POST /items/{id}/disconnect` | 只接受 Deactivated 且尚未断开的 Item。派生锁覆盖整个 Plaid `/item/remove` 调用，期间无法重新激活；成功后记录 `disconnected_at`，账本不变。组合操作先提交停用，再断开：如果断开失败（502），Item 仍是“已停用、仍连接”，可以重试 | 不动；check K13 阻止重新激活，直到重新连接流程实现（D18） |
| 通用 status 写入 | `PATCH /items/{id}/status` | **已退役（D3）**：没有必需的调用方，fail closed，一律返回 410，不读也不写数据库 | — |

digest 中包含转换类型，所以 activate 的预览不能拿去确认 reactivate，反之亦然。

与 `sync_all` 的交互：
- `sync_all` 在 fetch 前按 S3 选 Item，发布前在锁内用 S4 `_revalidate` 复核。若 Item 在 fetch 期间被停用，`_revalidate` 判定 `stale_item`：该 Item 的 buffer 被丢弃，cursor 不推进，其他 Item 正常发布。
- `jobs.tick` 的 `pft-jobs:` session lock 与这里无关，转换不需要它。
- 停用后定时同步跳过该 Item（S2、S3）。`request_sync` 选中 Deactivated 的 Item 时，返回“不是 Active”。

Plaid cursor 有效期：Plaid 文档没有承诺 cursor 永久有效。如果停用很久后重新激活，cursor 可能失效（Plaid 返回错误，或 `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` 之类）。现有的 `blocked` 路径会暂停该 Item 并保留 cursor，不会自动重置。重置 cursor 属于需要 owner 批准的操作（待决 D5）。

## 7. Remove institution data（只写设计，不实现）

目的：彻底移除一个机构的数据（例如误连，或关闭的账户）。

草案：
1. 只允许对 Deactivated 或 Rejected 的 Item 执行。必须先停用，确认 analytics 影响后再删除。
2. 影响预览同 §4：before = 当前账本，after = 去掉该 Item 后的账本；也会列出其他机构交易的分类变化（配对的另一半会从 transfer 变回 income/expense）。
3. 删除顺序（一个事务，派生锁下）：manual overrides（分类、类别、标签、权益）→ transactions → raw_transactions → statement_import_rows/batches → accounts → legacy_consumer_rows → sync_item_runs → items。然后对剩余 published 范围重新分类。
4. 删除前强制做一次备份，并记录该 Item 范围的指纹。

需要 owner 决定的问题（R-1..R-6 列在交接文档里）：
- R-1 是否需要先调用 Plaid `/item/remove`（停止计费、吊销 token）？先调还是后调？失败时怎么办？
- R-2 manual overrides 是删除，还是归档到审计表（以便误删后恢复）？
- R-3 账单导入的行（`source='statement'`）是否一起删除？
- R-4 删除后同一机构能否重新 Link？（现在 `_institution_exists` 会挡）
- R-5 是软删除（`removed_at` + 隐藏），还是硬删除？
- R-6 备份保留期内，被删数据仍在备份里；是否接受？

## 8. API 草案（6b）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/plaid/items/{id}` | Item 元数据 + 生命周期字段 + 账户列表 + 计数（不含 token/cursor） |
| GET | `/plaid/items/{id}/transactions-preview` | 该 Item 已规范化的交易（分页），用于 review 表 |
| GET | `/plaid/items/{id}/activation-checks` | §5 |
| POST | `/plaid/items/{id}/activation-preview` | §4，返回差异 + digest（POST，因为它会取锁并执行再回滚） |
| POST | `/plaid/items/{id}/activate` | body `{"preview_digest"}` |
| POST | `/plaid/items/{id}/reactivation-preview` | 重新激活的影响 + digest（预期为空） |
| POST | `/plaid/items/{id}/reactivate` | body `{"preview_digest"}` |
| POST | `/plaid/items/{id}/deactivation-preview` | 返回停用影响（预期为空）+ digest |
| POST | `/plaid/items/{id}/deactivate` | body `{"preview_digest"}` |
| POST | `/plaid/items/{id}/reject` | Pending → Rejected |
| POST | `/plaid/items/{id}/retry-onboarding` | Rejected → Pending |
| POST | `/plaid/items/{id}/maintenance/account-metadata` | 只限 Active：刷新已知账户的显示元数据（D16） |
| POST | `/plaid/transactions`、`/plaid/transactions/normalize`、`/plaid/accounts` | 只限 Pending onboarding（D16） |
| POST | `/plaid/items/{id}/disconnect` | 只限 Deactivated：Plaid `/item/remove`（D8） |
| PATCH | `/plaid/items/{id}/status` | 已退役：410（D3） |

## 9. 前端（6c）

`/plaid/items/<item_id>`：头部（机构、状态徽章、同步时间）→ “Prepare for review”：说明当前状态和下一步（Pending 需要先在后端完成拉取和规范化；今晚**不在页面上提供拉取按钮**，避免页面触发 Plaid 调用，待决 D7）→ 交易预览表 → Pre-activation checks → Activate 按钮。点击后先打开弹窗，弹窗里取预览并展示影响，用户手动点“确认激活”才会提交 digest。Deactivate 和 Reactivate 走同样的流程（各自的预览端点和确认按钮）。Activate **永远**需要手动确认，页面上不会自动触发。Pending 页面提供次要操作 **Cancel onboarding**（执行 reject），Rejected 页面提供 **Retry onboarding**（执行 retry-onboarding）。两者都要求二次确认，确认框明确写出“Rejected 状态下，已经 staging 的数据仍然保持 unpublished，不进入 scheduled sync，也不进入 analytics”。Retry 只做 Rejected → Pending，不导入、不 normalize、不发布、不激活（D17）。

## 10. 需要 owner 拍板的设计问题

已决定（2026-10-02，owner）：
- **D1 ✔** Production 迁移的 preflight 是强制的只读闸门。不自动提升、不悄悄改写任何非 active 的 Item；只要 Production 里有 Item 不处于迁移支持的状态，就在迁移前停止。→ §2.2 第 0 步。
- **D2 ✔** Pending 不参与定时同步、启动 catch-up 和普通的 Active 手动同步；Pending 的摄取/刷新只能是显式 onboarding 动作。→ `sync_enabled = status='active'`。
- **D3 ✔** 退役通用的 status PATCH。生命周期转换只能走显式的 activate / deactivate / reactivate 操作，各自带锁、校验和派生/发布语义。旧 PATCH 没有必需的调用方，所以 fail closed（410）。→ §6。
- **D4 ✔** Rejected 不能直接激活。必须先 retry-onboarding 回到 Pending，再走正常的 onboarding 准备、预览和激活检查。→ §6、K1。

- **D16 ✔** 拆分式的导入和 normalize 只用于 Pending onboarding；Active、Deactivated、Rejected 一律拒绝，相关测试改为调用原子同步的服务步骤。`/plaid/accounts` 只用于 Pending；Active 的元数据刷新只作为带锁、带校验的 maintenance 操作保留，不能替代同步。
- **D17 ✔** reject 和 retry 都有 UI，都要求二次确认；retry 只改状态。
- **D8 ✔** 停用默认**不**调用 `/item/remove`。另有单独的“停用并断开连接”选项（以及对已停用 Item 的“Disconnect from Plaid”），确认框写明重新激活需要重新连接。计费依据见 §12。
- **D14 ✔** 同步健康面板里的每个机构都有 “Manage institution” 链接，指向 `/plaid/items/<id>`。
- **M-1 ✔** 暂不合并。D15 彩排通过后，在同一个窗口内依次完成：合并 → preflight → 迁移 → api/jobs/web 三个镜像一起更新（见 runbook 的 “Lifecycle release window”）。
- **D12、D15** 已批准，在恢复副本上执行；命令清单见 `docs/PFT_LIFECYCLE_RESTORE_REHEARSAL_PACKET_2026-10-02.md`，等待逐条批准。

新出现、需要 owner 决定（不阻塞 merge，也不阻塞发布）：
- **D18** 断开连接之后怎么重新连接？新的 Link 会产生新的 Item 和新的 `transaction_id`，与旧交易重复；同时 `_institution_exists` 会挡住同一机构。需要设计“重连并对齐历史交易”，或者把断开定义为最终状态。另外，断开后已经失效的 token 仍以密文保存，是否清除也需要决定。

留到发布之后（owner 2026-10-02 决定）：D5–D7、D9、D13、R-1..R-6。

仍待决（原列表）：
- **D5** 重新激活时 cursor 失效（Plaid 报错），是否允许受控重置 cursor？默认：否。走现有 `blocked`/`sync_paused` 路径，等 owner 处理。
- **D6** Deactivated 的机构能否继续导入账单？默认否（L6 保持 Pending/Active）。
- **D7** 页面上是否提供 Pending 的“拉取/规范化”按钮（会调用 Plaid）？默认不提供，仍然走 runbook。
- **D8** 停用是否调用 Plaid `/item/remove`？默认否（保留 token 和 cursor，才能重新激活）。代价是 Plaid 可能继续按 Item 计费。
- **D9** 疑似重复的判定阈值（K9）。默认只提示，不阻止激活。
- Remove institution data：R-1..R-6（见 §7）。

## 11. 6b 验证结果（临时 PG16 集群，127.0.0.1:55439，用完删除）

**迁移彩排**（`scripts/pft_lifecycle_migration_rehearsal.py`）：
1. 用 `main`（`git archive main`）的代码建库、写入合成数据、分类，然后记录指纹；
2. 用本分支代码执行两次迁移（验证幂等），再记录指纹；
3. 两边各自再跑一次分类，再记录指纹。

四份指纹完全一致：transactions md5、raw_transactions md5、Item 状态/cursor/token 摘要、`external_classifications` 分类哈希，以及 284 行 analytics、6 个月的 `summarize_monthly_transactions` 哈希。证据在 `docs/evidence/institution-lifecycle-2026-10-02/`。

在同一个库上对 Ally 做激活预览：新增 6 笔；6 笔已有的 Chase Zelle 收入变成内部转账；2026-03..08 每月 income −75、net_savings −75。预览前后指纹一致（全部回滚）。

**测试**：`tests/test_institution_lifecycle.py`（9 项，`PFT_LIFECYCLE_SYNTHETIC_TEST=1`，fake Plaid client）：
- 跨机构 Zelle 配对改变已有交易的分类，预览与实际激活**完全一致**（digest 和全部差异字段都一致；激活后重新计算的差异也等于预览）；
- 预览之后账本有变化（新增 manual override）→ 激活被拒（409），什么都不改；
- 激活中途失败（分类写完后抛错）→ 整体回滚：状态、`activated_at`、分类都不变；
- 停用后 analytics、全部分类、transactions 都不变；配对仍然成立；再跑一次分类，写入集为空；
- 停用后定时同步跳过该机构（fake client 只收到 Chase 的请求），cursor 不动；`request_sync` 和 onboarding 拉取都拒绝该机构；
- 重新激活后，从停用前保存的 cursor（`b-2`）继续增量同步，停用期间的新交易被正常分类；
- pre-activation checks：K5、K6 失败时阻止预览和激活；修复后可以激活；
- Pending 数据在激活前不影响已发布分类；
- 迁移：从旧形状升级后，指纹和分类哈希完全一致；标志位符合推导规则；不能直接写生成列。

变异检查：把 `published` 改成只看 `active` 后，停用和重新激活两项测试失败。

### D1–D4 落实后的补充验证

- 新增测试 5 项（`tests/test_institution_lifecycle.py` 共 14 项）：
  - Production preflight 遇到 pending/disabled 时，在任何 DDL 之前阻止 `init_db`，schema 和行都不变；`api.lifecycle_preflight` 退出码为 2，只输出各状态数量；状态修正后放行；迁移应用后再加入的 Pending 不会阻止重跑。
  - 只有部分生命周期列时阻止迁移。
  - Pending 不进入定时同步、catch-up tick、全量手动请求，也不能被单独选中请求同步；显式 onboarding 拉取仍然可用。
  - 退役的 PATCH 对任何 Item 都返回 410，且不改数据库。
  - Rejected 的 activate/reactivate 预览和执行都返回 409；retry-onboarding 回到 Pending 后，走正常激活成功；reject 和 retry 都不改变账本。
- 变异检查：关掉 Production 闸门、把 Pending 加回 `sync_enabled`、允许 disabled 激活，各自都有对应测试失败。
- 彩排库（含 pending 和 disabled）：`python -m api.lifecycle_preflight` 退出码 2；`PLAID_ENV=production` 下 `init_db` 在 DDL 前停止，库保持不变（见 `production-preflight-blocked.json`）。非 Production 迁移后，旧代码与新代码的指纹仍然完全一致。

### D16、D17 落实后的补充验证

- 新增 3 项测试（lifecycle 测试共 17 项）：
  - Active、Deactivated、Rejected 调用三个拆分式路由和对应的模块 helper，全部返回 409，且在任何 Plaid 调用之前拒绝；Pending 照常 onboarding，并且不影响已发布账本。
  - Active 的 maintenance 只改账户显示名，财务账本、cursor、分类都不变；账户集合增减或类型漂移时返回 409 且不写入；Deactivated 被拒绝。
  - Retry onboarding 只改状态：不重新 normalize（被改动的 raw 未被应用）、不分类、不动 cursor、不进入同步，回到 Pending 后 K6 仍然要求重新 onboarding。
- 变异检查：把 onboarding 路由放宽到 active，或让 retry 顺带 normalize，对应测试都会失败。
- 前端：Jest 新增“取消接入需要二次确认、只写一次”和“重新接入只写 retry-onboarding 一次”。浏览器 QA 在三种宽度下覆盖了取消接入 → 重新接入 → 可以激活的完整流程。

## 12. Plaid 计费与 D8

根据 Plaid 官方文档（[Plaid pricing and billing](https://plaid.com/docs/account/billing)，2026-10-02 查阅）：
- Transactions 采用**订阅费模式**（`/transactions/refresh` 除外，它按次计费）。
- “只要 Item 存在有效的 `access_token`，每个 Item 每月收取订阅费。” 用 `/item/remove` 删除 Item 才会结束订阅。
- 按 UTC 自然月计费，月中创建或删除的 Item **不按比例折算**。
- 即使没有任何 API 调用，或者 Item 处于错误状态（例如 `ITEM_LOGIN_REQUIRED`），只要订阅有效就照常收费。
- 文档里没有价格表。Pay-as-you-go 和 Growth 套餐的单价，只在 Plaid Dashboard 申请 Production 时的最后一页显示；Custom 套餐由销售报价。**我们实际使用的套餐和单价不在仓库里，需要你到 Plaid Dashboard 的 Billing 页面确认。**

所以，停用但保持连接的 Item 会继续按月收费。这正是 D8 默认选择的代价：保留 token 和 cursor，重新激活才能从原 cursor 继续。需要停止计费时，用“停用并断开连接”。断开当月仍然收取整月费用。

### 实现

- 新列 `items.disconnected_at`（可空）。迁移和 preflight 的生命周期列中都包含它。
- `POST /plaid/items/{id}/deactivate` 带 `{"preview_digest", "disconnect": true}`：先按正常流程提交停用（带 digest 校验），再执行断开。
- `POST /plaid/items/{id}/disconnect`：只接受 Deactivated 且未断开的 Item。在派生锁内调用 Plaid `/item/remove`，成功后写入 `disconnected_at`；失败时返回 502，什么都不写。
- Check K13 “Plaid connection”：已断开 → fail，重新激活预览和执行都返回 409。
- 前端：Active 页面有 “Deactivate”（默认保持连接，说明会继续计费）和单独的 “Deactivate and disconnect”。Deactivated 页面有 “Disconnect from Plaid”。断开后显示 “Disconnected” 徽章和提示，Reactivate 按钮禁用。
- 测试：
  - `test_deactivation_keeps_the_plaid_connection_by_default`：没有任何 Plaid 调用；
  - `test_deactivate_and_disconnect_removes_the_item_and_blocks_reactivation`：fake client 收到 `/item/remove`，账本不变，K13 fail；
  - `test_failed_disconnect_leaves_a_connected_deactivated_item_to_retry`。
