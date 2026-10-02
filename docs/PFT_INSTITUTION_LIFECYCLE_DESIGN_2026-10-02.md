# Institution lifecycle：Pending / Active / Deactivated 设计

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
| S1 | `api/jobs.py` `request_sync` 选定 Item 校验 | `status='active'` | 同步 | `sync_enabled AND published`（即 Active） |
| S2 | `api/jobs.py` `tick` 到期 Item | `status='active' AND NOT sync_paused` | 同步 | `sync_enabled AND published AND NOT sync_paused` |
| S3 | `api/services/sync_all.py` `sync_all` 选 Item | 同上 | 同步 | 同上 |
| S4 | `api/services/sync_all.py` `_revalidate` 发布前复核 | `status != 'active'` 即 stale | 同步 | 复核同一谓词；Item 在 fetch 与 publish 之间被停用 → `stale_item`，整 Item 回滚，cursor 不动 |
| S5 | `api/routes/plaid.py` `POST /plaid/transactions`、`/accounts` | pending/active | 同步（onboarding 手动拉取） | `sync_enabled`（Pending、Active）；Deactivated 拒绝（409，需先重新激活） |
| S6 | `api/services/persistence.py` `persist_consumer_transactions`、`persist_account_metadata` | pending/active | 同步 | 同 S5 |
| S7 | `api/services/derivation.py` `normalize_item_transactions` | pending/active | 同步（派生，紧跟拉取） | 同 S5 |
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
| C4 | `activate_item` | pending/active/disabled | 状态转换 | §5 |
| X1 | `api/routes/plaid.py` `_institution_exists` | 不看状态 | 唯一性 | 不变：Deactivated 的机构不能重新 Link，只能重新激活 |
| X2 | `scripts/pft_m6_fingerprint.py`、`pft_m5_benchmark.py` | 读/写 status | 工具 | 指纹加入新列；benchmark 写入时补齐新列 |

注：`lock_consumer_derivation` 锁住用户的**全部** Item 和 Account，不看状态，不需要改。

## 2. 状态模型

### 2.1 选择

用两个布尔列表达范围，`status` 保留为可读标签，用 CHECK 约束把三者绑死：

| 状态 | `status` | `sync_enabled` | `published` | 同步 | 账本 | 分类输入 |
|---|---|---|---|---|---|---|
| Pending | `pending` | true | false | 只允许 onboarding 手动拉取 | 否 | 否（只出现在预览里） |
| Active | `active` | true | true | 定时 + 手动 | 是 | 是 |
| Deactivated | `deactivated` | false | true | 否 | 是 | 是 |
| Rejected（旧 `disabled`） | `disabled` | false | false | 否 | 否 | 否 |

```sql
CHECK ((status='pending'     AND sync_enabled     AND NOT published)
    OR (status='active'      AND sync_enabled     AND published)
    OR (status='deactivated' AND NOT sync_enabled AND published)
    OR (status='disabled'    AND NOT sync_enabled AND NOT published))
```

理由：
- 每类范围只看一列：同步看 `sync_enabled`（定时同步再加 `published`，见 2.3），账本和分类输入都看 `published`。三类查询不会再各自解释 `status`。
- 保留 `status` 有两个好处。一是回滚安全：旧镜像只读 `status='active'`，迁移后对现有数据的结果不变。二是人能直接看懂。
- CHECK 约束让两个布尔列和标签无法不一致，也就不存在“published 但 status=pending”这种组合。
- 另加审计列：`activated_at`、`deactivated_at`（TIMESTAMPTZ，可空），以及 `activation_digest`（最近一次激活所确认的预览摘要）。

不选纯枚举：每个查询都要写 `status IN (...)`，“Deactivated 仍计入账本”这条规则会散落在十几处，漏改一处就会让 analytics 悄悄变化。

### 2.2 迁移（`migrate_institution_lifecycle`，幂等）

1. `ADD COLUMN IF NOT EXISTS sync_enabled BOOLEAN`、`published BOOLEAN`、`activated_at`、`deactivated_at`、`activation_digest`。
2. 只回填 NULL 行：`active → (true, true)`，`pending → (true, false)`，`disabled → (false, false)`。如果遇到其他 `status` 值，直接 `RAISE`，不猜。
3. 设置 `NOT NULL`，默认值为 `(true, false)`，与 pending 一致。
4. 把 `ck_items_status` 扩展为四个值，并加 `ck_items_lifecycle`。
5. 加索引 `ix_items_user_sync (user_id, sync_enabled, published)`。
6. 不改任何交易、分类、cursor、token。

预期 Production 现状：全部 Item 都是 `active` → 迁移后全部为 Active + published。这一点在 Production 执行前需要只读确认（待决 D1），今晚不连 Production。

### 2.3 迁移前后不变量

迁移前后必须**逐字节一致**：
- 每个 Item 的 `transactions_cursor`、`access_token` 摘要、`status`；
- `transactions` 全表（去掉时间戳列）的 md5；
- `external_classifications` 的结果（分类哈希）；
- analytics：对每个有数据的月份调用 `summarize_monthly_transactions`，结果的 JSON 哈希；
- 迁移后立刻跑一次 `classify_active_transactions`，写入集必须为空。

6b 在临时集群上，用带现有数据形状的合成库验证这些不变量：Active 多机构、禁用的投资账户、手动 override、账单导入行、已删除行、一个 pending 和一个 disabled Item。

定时同步谓词用 `sync_enabled AND published`，而不是只看 `sync_enabled`：现状是 pending 只靠手动拉取，不进定时同步。是否改为让 Pending 也进定时同步，列为待决 D2。

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
| K1 | 状态可激活 | `status IN ('pending','deactivated')`；`disabled` 必须先改回 pending（待决 D4） | fail |
| K2 | 已发现账户 | 至少一个 `consumer_transactions_enabled` 账户 | fail |
| K3 | 账户归属一致 | `validate_consumer_activation` 的归属校验（raw 与 normalized 的 account 一致，账户属于该 Item） | fail |
| K4 | 禁用账户上没有新消费数据 | 同上，与 `legacy_consumer_rows` 比对 | fail |
| K5 | 已有初始同步 | `transactions_cursor IS NOT NULL` | fail |
| K6 | 规范化完整 | 启用账户上每条未删除的 raw 都有 normalized 行，且值一致（复用 `_normalized_differs`）；源数据校验通过（`validate_normalization_input`） | fail |
| K7 | 已发布分类是最新的 | 用 `published` 范围重算一次，结果与存储值一致（写入集为空）。否则 before 快照就不是用户当前看到的 analytics | fail |
| K8 | 同步状态健康 | `NOT sync_paused`，`metadata_warning IS NULL`，最近一次 `sync_item_runs`（如果有）不是 blocked | warn |
| K9 | 交易与已有数据没有冲突 | 新 Item 的 transaction_id 不与其他 Item 重复（主键已经保证，这里显式报告），也没有疑似重复（同金额、同日期，对方账户在另一个 published Item，且双方描述都不像转账）→ 列出条数 | warn |
| K10 | 日期范围 | 报告最早和最晚交易日期；早于已发布账本最早日期 → warn（会改写历史月份） | warn |
| K11 | 影响预览可算 | §4 预览成功，返回摘要 | fail |
| K12 | 没有进行中的同步 | `sync_runtime_state.running_sequence` 为空，或已处理 | warn（激活本身会等锁） |

## 6. 状态转换与 atomic workflow、advisory lock、cursor 的关系

所有转换都在 `lock_consumer_derivation` 下进行（事务级 advisory lock，加上全部 Item 和 Account 的行锁）。它和 `sync_all` 的发布阶段、手动拉取、规范化、review 写入、账单导入用的是同一把锁，所以任何转换都不会和发布交错。

| 转换 | 端点 | 做什么 | cursor |
|---|---|---|---|
| Pending → Active | `POST /items/{id}/activate`（带 digest） | checks K1–K7 → `(sync_enabled, published) = (true, true)`，`activated_at=now()` → `classify_active_transactions` → 校验摘要 → 提交。任何一步失败，整体回滚 | 不动 |
| Active → Deactivated | `POST /items/{id}/deactivate` | `(false, true)`，`deactivated_at=now()`；**不重新分类**（输入不变）；断言分类写入集为空 | 不动；token 也不动；不调用 Plaid `/item/remove` |
| Deactivated → Active（重新激活） | `POST /items/{id}/activate`（带 digest） | 同 Pending → Active。由于 Deactivated 已经 published，预览差异通常为空，但仍然要求确认 | 不动；下一次定时同步从**已保存的 cursor** 增量拉取，补上停用期间的 added/modified/removed |
| Pending → Rejected | 保留 `PATCH .../status {"status":"disabled"}` | 现状 | 不动 |

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
| POST | `/plaid/items/{id}/deactivate-preview` | 返回停用影响（预期为空）+ digest |
| POST | `/plaid/items/{id}/deactivate` | body `{"preview_digest"}` |
| PATCH | `/plaid/items/{id}/status` | 兼容：`disabled` 保留；`active` 改为要求 digest（或 410），见待决 D3 |

## 9. 前端（6c）

`/plaid/items/<item_id>`：头部（机构、状态徽章、同步时间）→ “Prepare for review”：说明当前状态和下一步（Pending 需要先在后端完成拉取和规范化；今晚**不在页面上提供拉取按钮**，避免页面触发 Plaid 调用，待决 D7）→ 交易预览表 → Pre-activation checks → Activate 按钮。点击后先打开弹窗，弹窗里取预览并展示影响，用户手动点“确认激活”才会提交 digest。Deactivate 走同样的流程，用确认弹窗。Activate **永远**需要手动确认，页面上不会自动触发。

## 10. 需要 owner 拍板的设计问题

- **D1** Production 迁移前做只读确认：是否全部 Item 都是 `active`？是否存在 `disabled` 行？（今晚不连 Production。）
- **D2** Pending 是否进入定时同步？默认否（保持现状：只有手动拉取）。改为是会自动产生 Plaid 调用。
- **D3** 旧的 `PATCH /items/{id}/status {"status":"active"}`（不带预览）怎么处理：保留、改为要求 digest，还是返回 410？默认：要求 digest，缺失时返回 409。
- **D4** Rejected（`disabled`）能否直接激活？现状可以。默认：必须先恢复为 Pending（需要新的端点，今晚不做），激活检查 K1 判为 fail。
- **D5** 重新激活时 cursor 失效（Plaid 报错），是否允许受控重置 cursor？默认：否。走现有 `blocked`/`sync_paused` 路径，等 owner 处理。
- **D6** Deactivated 的机构能否继续导入账单？默认否（L6 保持 Pending/Active）。
- **D7** 页面上是否提供 Pending 的“拉取/规范化”按钮（会调用 Plaid）？默认不提供，仍然走 runbook。
- **D8** 停用是否调用 Plaid `/item/remove`？默认否（保留 token 和 cursor，才能重新激活）。代价是 Plaid 可能继续按 Item 计费。
- **D9** 疑似重复的判定阈值（K9）。默认只提示，不阻止激活。
- Remove institution data：R-1..R-6（见 §7）。
