# 恢复副本彩排命令清单（D15 + D12）— 2026-10-02

**状态：D15 通过，D12 全部技术覆盖已完成并通过（含 fresh 真实备份副本上的有效 synthetic Pending onboarding/activation）。临时集群均已清理。latency 正式接受仍按本文既有 owner 判定标准；无预设数值 SLA。见最终及补充执行记录。**

目的：把最近一份 Production 备份恢复到一次性的临时集群，在副本上依次执行旧代码指纹、严格 preflight、迁移、新代码指纹，并测量预览和激活的耗时。全程**不连接 Production**（不连它的数据库，不执行 docker 命令），不调用 Plaid，用完删除集群。

所有步骤都由 `scripts/pft_lifecycle_restore_rehearsal.sh STEP` 执行，每一步就是下表中的一条命令。脚本内容就是审阅对象。

## 本次重新执行授权

owner 已接受 D12 timing，并授权本次彩排按清单顺序自主执行，无需逐条批准：R1 后按 mtime 从新到旧选择首个 R2 验证成功的 Production 备份，结果 JSON 记录文件名及选择依据。开始前脚本和本文必须已提交，每一步前确认 tracked/untracked 工作树及 staged diff 均为空；执行期间冻结脚本。如需修订脚本，停止并记为待决事项。R5 被拦或 R7 `all_identical` 不为 true 时立即停止后续步骤；无论成功失败均执行 S9，仅保留结果 JSON。此授权不允许绕过任何 safety gate，也不涉及 Production release。

## 隔离措施

- **临时集群**：PostgreSQL 16，`listen_addresses=''`，**不开 TCP**，只用私有 Unix socket 目录（mode 0700）。认证方式为 `peer`，拒绝所有 host 连接。端口号 55441 只用于 socket 文件名。
- **数据库**：只用 `pft_restore_lifecycle_20261002`。Python 工具在以下任一情况下都会拒绝运行：非 `pft_restore_*` 库、非私有 socket、服务器开着 TCP、设置了 `PLAID_ENV=production` 或 `EXPECTED_DATABASE_NAME`。
- **Plaid**：脚本会清空 `PLAID_*` 环境变量，并把 `plaid.ApiClient` 替换为会直接报错的桩。
- **备份文件**：只读。`pg_restore` 直接从备份目录读取，**不复制**备份。
- **结果文件**：只含计数、哈希和耗时，不含任何行、ID、cursor 或 token；放在 `$PFT_REHEARSAL_DIR/results/`，权限 0600。是否把摘要写进仓库，等你看过结果再定。
- **凭据**：不读取任何 `.env*` 或凭据文件，也不需要它们。副本里的 access token 是 Fernet 密文，整个过程不会解密。

## 环境（每个 shell 先设置）

```sh
cd /home/randyli/code/pft-institution-lifecycle
export PFT_REHEARSAL_DIR=$HOME/.local/share/pft/rehearsals/lifecycle-20261002
export PFT_BACKUP_SOURCE_DIR=/mnt/c/Users/tianr/PFTBackups/Production
# 在 R1 之后由你选定：
export PFT_REHEARSAL_BACKUP=$PFT_BACKUP_SOURCE_DIR/<chosen>.dump
export PFT_REHEARSAL_OLD_COMMIT=<R2 输出的 resolved_application_commit>
```

开始前：`scripts/pft_lifecycle_restore_rehearsal.sh S0`（**[STATE]**，只创建配置的本地私有目录并验证路径、当前用户所有权和 0700 权限；路径必须为绝对、规范、非根且无符号链接的路径，直接父目录必须已存在且为目录，不能创建或修改父目录）。

## 命令清单

| 步骤 | 类别 | 做什么 | 读/写 | 停止条件 |
|---|---|---|---|---|
| S0 | **STATE** | 在已存在的直接父目录下只创建最终彩排目录（0700），验证路径和所有权；输出安全路径/状态 | 只写最终本地目录 | 父目录不存在或不是目录，路径、所有权或权限不符合要求 → 停 |
| R1 | READ | 按文件系统修改时间从新到旧列出最多 12 个 manifest（`filename`、`size`、UTC `modified_at`）；不读取内容、不自动选择 | 读备份目录元数据 | 候选不是普通文件或是符号链接 → 停 |
| R2 | READ | 校验 owner 选定的 `.dump` 和同目录同名 `.json`；输出 manifest 字段（时间、kind、size、sha256、schema_sha256、application_commit、format），`resolved_application_commit`、`actual_size`、`actual_sha256`、`table_data_count` | 只读所选 manifest 和 dump，执行 `pg_restore -l` | sha256 或已记录的 size 不一致、字段/文件缺失、映射不明确、manifest 格式错误或 archive 不可读 → 非零退出并停 |
| S1 | **STATE** | `initdb` 一次性集群（peer 认证、拒绝 host 连接） | 写 `$PFT_REHEARSAL_DIR/data` | 目录已存在 → 拒绝 |
| S2 | **STATE** | 启动集群（不开 TCP） | 本地进程 | — |
| R3 | READ | 确认 `listen_addresses=''`，以及 data_directory 和版本 | 读副本 | 不是该目录 → 停 |
| S3 | **STATE** | `createdb` + `pg_restore --exit-on-error --no-owner --no-privileges`，输出各状态的 Item 数量 | 读备份，写副本 | restore 失败 → 停 |
| S4 | **STATE** | 用 `git archive` 取出写这份备份的代码版本（`application_commit`） | 写私有目录 | commit 不存在 → 停，先确认 commit |
| R4 | READ | 旧代码指纹（只读事务）：表哈希、分类哈希、analytics 哈希 | 读副本 | — |
| S5 | **STATE**（副本） | 旧代码重新分类后再取指纹（预期写入集为空） | 写副本 | 与 R4 不同 → 记录并停，说明备份时分类本来就不是最新的 |
| R5 | READ | 新代码的严格 Production preflight（`api.lifecycle_preflight`） | 读副本 | 退出码 2 = Production 现状会被闸门拦住 → 记录各状态数量，**停下来报告** |
| S6 | **STATE**（副本） | 新代码迁移，先过严格闸门 | 写副本 | 退出码 2 → 停 |
| S6b | **STATE**（副本，需单独批准） | 只在 S6 被拦时使用：用非 Production 闸门迁移副本，让 D15/D12 能继续。**不改变 Production 的结论** | 写副本 | — |
| R6 | READ | 新代码指纹 | 读副本 | — |
| S7 | **STATE**（副本） | 新代码重新分类后再取指纹 | 写副本 | — |
| R7 | READ | 比较四份指纹（忽略耗时） | 读结果文件 | `all_identical` 不为 true → D15 不通过 |
| S8 | **STATE**（副本） | 测量 D12 耗时：ledger 快照、全量分类；对最大的 Active Item 做停用预览和执行、重新激活预览和执行；每个 Pending Item 做激活检查，通过则预览并激活（只改副本） | 写副本 | 预览与执行不一致 → D12 不通过 |
| S8p | **STATE**（fresh 副本，owner 已授权） | 通过现有 lifecycle test 的 Pending 创建及 onboarding 服务路径加入 synthetic Item，行数取副本中最大 Active consumer Item 的未删除 raw 行数；通过真实 checks 后测激活 preview/apply | 只写新副本 | 隔离/schema/flags/checks、preview rollback、全表原数据保护、source/cursor、分类或 parity 任一不符 → 非零退出；S9 清理 |
| S9 | **STATE** | 停止集群，删除 `data`、`sock`、`old_src` 和日志，只保留 `results/*.json`（0600） | 删除本地临时数据 | — |

收尾时，在 S9 之后由你决定 `results/` 的去留。如需删除，执行 `rm -rf -- "$PFT_REHEARSAL_DIR"`（**[STATE]**）。

## 预期与判定

- **R1/R2 备份合同**：由 owner 选择规范绝对路径 `$PFT_BACKUP_SOURCE_DIR/<stem>.dump`（不接受 `..` 或符号链接路径），manifest 必须为同目录的 `<stem>.json`；二者必须是普通文件且不能是符号链接，不使用 manifest 字段指定备用文件路径。R2 必需字段为 `created_at`、`kind`、`sha256`、`schema_sha256`、`application_commit`、`format`：`created_at` 必须为备份工具输出的 UTC `datetime.isoformat()` 格式（`+00:00`，可含六位微秒）；`kind` 必须为 daily/weekly/monthly/extra；两种 SHA256 必须为 64 位小写十六进制；`application_commit` 必须为运行指南中 `git rev-parse HEAD` 输出的完整 40 位小写 Git hash（或下述唯一已验证 release label 映射），解析后的 revision 必须经 `git rev-parse --verify <SHA>^{commit}` 解析为本 repo 中的同一 commit；`format` 必须为 `pg_dump-custom`。拒绝重复字段。`size` 如有记录必须为非负整数且与实际字节数一致；未记录时输出 `size: null`，仍验证 SHA256。R2 仅在所有校验及 archive inspection 成功后输出结果；不输出 archive listing 或错误中的原始内容。
- **D15 通过**：R7 输出 `all_identical: true`，也就是迁移前后、重新分类前后，表、Item、分类和 analytics 的哈希全部一致。
- **D12**：S8 输出各项耗时（单位秒），以及每个操作的 `preview_equals_apply`。`*_apply_seconds` 约等于派生锁被持有的时间，这段时间里同步和 review 写入都要等待。是否可以接受由你判定。
- **R5 或 S6 被拦**：说明当前 Production 有非 active 的 Item，D1 闸门会阻止真实迁移。要先决定如何处理这些 Item，然后才能进入发布窗口。S6b 只用于在副本上继续完成彩排。

## 合成数据预演（已完成）

我用 `main`（47183eb）的代码建了一个合成库（Chase、Amex、Pending 的 Ally、一个 Rejected），用 `pg_dump -Fc` 导出成合成“备份”，再按上表顺序执行了一遍全部步骤：

- R5 和 S6 正确停止（`disabled=1, pending=1`，退出码 2），并且没有执行任何 DDL。
- S6b 迁移了副本。R7 输出 `all_identical: true`。
- S8：ledger 快照 0.043s，全量分类 0.013s；激活 Pending 的预览 0.040s、执行 0.038s；停用和重新激活都在 0.07s 以内；所有 `preview_equals_apply` 都为 true。数据规模为 290 笔交易。
- S9 清理后没有残留的 socket 监听，所有合成文件都已删除。

真实备份的规模更大，耗时以真实彩排为准。

## 真实彩排执行记录（2026-10-02）

- 代码：`feature/institution-lifecycle`，彩排工具提交 `6bc942de83bd9a77c989e69244baa14e74af5528`。owner 随后授权自主选择最新有效备份并执行到 S9；安全检查失败仍须停止。
- **父目录 bootstrap（单独授权的本地操作，不属于 S0）**：检查 `/home/randyli/.local/share/pft` 及其祖先均为真实目录、无符号链接且属于当前用户；PFT 目录权限为 0700，`rehearsals` 不存在。执行 `mkdir -m 0700 /home/randyli/.local/share/pft/rehearsals`，仅创建这个本地 app-state 子目录，不创建或修改其他祖先。S0 本身仍不允许递归创建父目录。
- **S0**：通过 wrapper 执行成功；`/home/randyli/.local/share/pft/rehearsals/lifecycle-20261002` 路径、当前用户所有权及 0700 权限均通过验证。
- **R1**：通过 wrapper 只读列出 12 个候选。最新 manifest 为 `pft-daily-20261002T193523283029Z.json`，文件大小 435 字节，文件系统修改时间 `2026-10-02T19:35:23.482944+00:00`；因此选定同名 `.dump` 做 R2 校验。
- **R2**：退出码 1，安全错误为 `refusing: manifest application_commit must be a full Git commit hash`。在计算 dump SHA256、archive inspection 之前停止，没有输出被拒绝的 metadata，也没有绕过 wrapper 读取其内容。没有改写 manifest 或备份，也没有选择其他备份绕过这个失败。
- **结果**：D15、D12 尚未完成；S1–S9 均未执行，没有临时 PostgreSQL 集群或恢复副本需要清理。仅保留上述本地私有目录和此执行记录。未连接 Production 数据库、调用 Plaid、修改 cloud、merge 或 push。
- **当时的阻塞项**：需要明确如何处理真实 manifest 与当前 `application_commit` 格式检查的不一致，再恢复执行。此时不能声称该备份完整性已验证。

### application_commit 调查与候选选择（owner 随后授权）

- `api.backup.backup()` 原样记录环境变量 `PFT_APP_COMMIT`，没有强制 SHA 格式；`api.backup.restore()` 只校验 archive 的 SHA256 和 size。运行指南推荐完整 Git SHA，但后续 jobs overlay 的发布记录明确使用 release label（见 `docs/PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md` 的 Phase 1 Step 4）。因此 release label 是生产者允许的 provenance，不是短 SHA，也不能直接作为本彩排的旧代码 revision。
- 只读调查最近 12 个 manifest 的 approved metadata：最新五个 `application_commit` 均为非十六进制 label，没有发现短 SHA。不能从 label 猜测或截取 commit；这些候选不满足本彩排的旧代码定位要求，不修改它们。按 mtime 顺序，下一个候选是 `pft-daily-20260929T193412879163Z.dump`，记录完整 SHA `2b413550433e83db151ef1f62ad98b26d70fbd9e`。
- R2 保持完整 40 位小写 SHA 要求，并新增 `git rev-parse --verify <SHA>^{commit}` 校验，要求它在本 repo 中存在且解析结果与原 SHA 完全相同；拒绝未知 object、非 commit object 及 label。若 R2 失败，不声称该候选有效。
- 新增未知 SHA、非 commit object、release label 的合成回归测试；测试使用临时合成 Git repo，不依赖真实备份或数据库。

### 恢复副本执行结果及清理

- 工具修订提交 `5a5992d`；21 个合成 wrapper 测试、shell syntax、`git diff --check` 均通过。
- **R2**：`pft-daily-20260929T193412879163Z.dump` 验证通过；SHA256 `e40c88f8a5544faa498291794560b3f67ae715f26009983f0e7cba9d8d7b0516`，size 492321 字节，15 个 TABLE DATA；`application_commit` 在本 repo 中存在。
- **S1/S2/R3/S3/S4**：通过 wrapper 创建并验证 PostgreSQL 16.15 的 peer-auth、无 TCP、私有 socket 临时集群；只恢复到 `pft_restore_lifecycle_20261002`，导出已验证的旧代码 revision。副本有 5 个 Active Item。
- **R4/S5**：2620 笔 transactions/raw，2605 个 analytics rows，25 个月。R4 和旧代码重新分类后的 S5 在 R7 的全部七个 preservation key 上相同。旧 classifier 报告 `reclassified_count=2564`（旧代码会重新写入分类；这不是零写入证明），但所有排除时间字段的表哈希、Item、分类和 analytics 指纹一致。
- **R5**：副本严格 lifecycle preflight 通过（5 Active，`applied=false`，无 blocker）；这仅描述该备份副本，不声称当前 Production preflight 会通过。
- **S6**：非零退出；`api.migrations.migrate_manual_categories()` 检测到旧 `FOOD_AND_DRINK` manual overrides，报 `Explicit reviewed Dining migration required before schema migration`。没有绕过此独立 safety gate。整个 `init_db()` 在单个事务中；异常回滚，随后只读 R5 再次确认 lifecycle 未应用、5 Active 不变。R6/S7/R7/S8 未执行；D15/D12 不能判定通过。
- **S9**：停止临时集群并删除 data、socket、旧源码和日志。核验只剩 `results/` 的四个有效 JSON 文件，均为 0600：`before.json`、`before_reclassified.json`、`preflight.json`、`migrate.json`。S6 没有输出 JSON，因此空的 `migrate.json` 被替换为安全的失败阶段/错误/status counts 摘要，不含任何金融行或 ID。收尾 R2 再次通过，源备份 SHA256 和 size 保持不变。
- **真正阻塞项**：最近的备份缺少可直接解析的 old-code commit provenance；可定位 commit 的旧备份又早于已审阅的 Dining 迁移。本 packet 没有授权绕过或重定义四指纹比较来消化这项前置金融数据迁移。需要一份可证明代码 provenance 且已满足 Dining 前置条件的备份，或独立审阅的副本前置迁移及 baseline 比较方案。
- 全程未连接 Production、未修改源备份、未调用 Plaid、未改 cloud、未 push/merge/deploy。

### 最新 post-Dining 备份的已验证 provenance（后续调查）

- 后续调查找到可验证的精确 label：`sdw-p2-b646fb9-derivation-over-1d17e2b59fa4be74af41f60125f41084698049424e0b4d77376db1fe41cc74c7`。它不是任意文本或猜测截取的短 SHA。
- `docs/PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md` 的 Phase 1 执行记录验证 base image `1d17e2b5…` 全部 34 个 Python 文件等于 `a047b0f4b32c2db23203fbab9b25cd5fe7678400`；Phase 2 执行记录验证 derivation overlay 后全部 34 个文件等于 `6ac9612f97479ed96eb69be55864437652f33a00`。本地 Git 再确认 api/statement_imports 的唯一区别为 `api/services/derivation.py`，且该 blob 等于 `b646fb9e9d52e795f177cf9c4d2f202f5d71f99a` 的同一 blob。
- R2 只允许这个精确 label 映射到 `6ac9612f97479ed96eb69be55864437652f33a00`，运行时重新验证上述 Git source 关系及 commit 存在。其他 label、source 关系变化、缺失 Git object 均失败。输出保留原 `application_commit`，新增 `resolved_application_commit` 供 S4 使用。不修改 manifest。
- 因此最新候选 `pft-daily-20261002T193523283029Z.dump` 可重新接受完整 R2 校验，再恢复到一次性副本确认 Dining 前置条件。不需要执行 copy-only Dining 数据迁移；旧失败过程已清理。

### 最终执行记录：最新 post-Dining 真实备份

- 代码修订 `188bbc9`；新增精确 label 映射和 source 关系 regression coverage。22 个 wrapper 测试通过，shell syntax 和 `git diff --check` 通过。
- **R2**：最新 backup SHA256 `25059442a9fdd066bbfbb1be44e433bd414508218f31c7427c32a95cf07b87b6`，499147 字节，15 个 TABLE DATA；原 label 经上述记录解析到 `6ac9612f97479ed96eb69be55864437652f33a00`。所有完整性校验通过。
- **S0–S5**：重用已验证私有目录，创建新 peer-auth/socket-only PostgreSQL 16.15 集群，只恢复一次性副本并导出 resolved commit 的旧代码。副本有 6 个 Active Item、14 个 account、2640 个 transactions/raw、2619 个 analytics rows、26 个月；R4 与 S5 的 preservation fingerprints 全部相同。
- **R5/S6**：严格 preflight 通过；migration 在副本上成功，0.051s。不需要 S6b，也不需要额外 Dining migration。没有对当前 Production 执行 preflight 或 migration。
- **R6/S7/R7（D15）**：四份结果的七个 preservation key 全部相同，`all_identical: true`。表、Item、分类和 analytics 无差异。旧/新 reclassification 的 `classified_count` 都是 2578，不将此计数解释成实际改写行数。
- **S8（D12）**：ledger snapshot 0.134s；分类 0.057s；最大 Active Item 停用 preview 0.224s / apply 0.248s，重新激活 preview 0.382s / apply 0.400s。两项 `preview_equals_apply` 均为 true；账本 impact 的 changed/new/removed/month counts 全为 0。
- **D12 coverage 限制**：此 backup 全部 Item 都是 Active，S8 没有 Pending 激活目标。没有伪造 Pending 状态、创建金融行或绕过 checks，因此不能声称已测真实备份的 Pending activation timing。合成数据的 Pending activation 结果仍见上方预演；真实数据 activation timing 如为 release 必需，仍需一个有效 Pending 副本场景。
- **S9**：集群成功停止，data、socket、old_src、log 已删除；只剩 8 个有效 JSON，全部 mode 0600：before、before_reclassified、after、after_reclassified、preflight、migrate、compare、timing。此轮结果替换旧失败轮次同名结果，旧失败摘要保留在本文。
- 收尾再次执行 R2，source backup SHA256/size 未变。未修改 source backup 或 Production/cloud，未调用 Plaid，未 push/merge/deploy。是否接受约 0.400s 的最大 apply lock timing 仍由 owner 判定。

### D12 Pending activation 补充方案（owner 已授权自主执行）

- acceptance 文本没有数值 latency threshold；已测 deactivate/reactivate 和 classification 的 parity/保存要求通过，latency 的正式接受按原标准仍由 owner 判定，不能把任意自设 threshold 写成已有标准。
- 先按 R2 验证同一最新 backup，S0/S1/S2/R3/S3 创建 **fresh** 副本，R5/S6 通过严格闸门迁移，然后只通过 wrapper 执行 S8p，最后 S9。以前 D15 及 timing JSON 保留；补充结果写 `pending_activation.json`（0600）。
- S8p 复用 `tests/test_institution_lifecycle.py` 的有效 fixture 模式：新 ORM Item 直接以合法初始 Pending 状态创建；`persist_account_metadata` 建立 consumer depository account；`persist_consumer_transactions(..., statuses=ONBOARDING_STATUSES)` 写 synthetic payload 并保存 synthetic cursor；`normalize_item_transactions` 完成 normalization。不把已有 Active Item 改为 Pending，不伪造真实 institution/token/cursor，不调用 Plaid，也不改应用行为。
- synthetic payload 全为可分类 purchases，跨 26 个月，数量等于最大的 Active consumer Item；原备份账本为真实的 classification/preview scale。该测量是代表性 fixture 在真实账本规模上的 activation，不声称它是实际待接入 institution 或最坏情况。
- 要求 Pending 未发布、checks 全部不 fail、preview 后全部表全行哈希和 Pending 状态原样恢复、apply 与 preview 各项 diff/digest 一致、新 Item 变为 Active/sync-enabled/published、cursor 原样、全部 fixture 行正确分类且发布；所有原备份行（包括 audit/timestamps）哈希保持相同。source-only 哈希只排除本次合法分类/lifecycle 变动字段及 fixture 分类服务预期更新的 updated_at（原备份行仍单独要求全行精确不变），除此之外所有 source/override/token/cursor 均保存。不输出或保存 IDs、行或 token。
- `activation_apply_core_seconds` 测应用转换本身；`activation_apply_and_validation_seconds` 包含本次 rehearsal 的额外全表校验及 commit，不把校验额外开销冒充应用 latency。任一校验失败在 commit 前回滚，commit 后再核验原行和 source；错误输出仅安全摘要。

### D12 补充执行结果：有效 Pending onboarding

- R2 再确认最新 backup 未变，fresh copy 中的 6 Active 通过严格 R5/S6；没有对实际 Item 降级或改变 source backup。新 Item 通过已有 lifecycle test / Pending persistence / normalization 路径创建，checks 全部通过。
- fixture 为 1510 笔跨 26 个月的 synthetic purchases（等于最大 Active consumer Item 的未删除 raw 行数），叠加 2619 个真实 baseline analytics rows。只代表该规模和构成，不声称未知 future Item 的绝对 worst case。
- preview **0.521s**，apply core **0.454s**；含额外全表 preservation 校验及 commit **0.679s**。`preview_equals_apply`、preview 全行 rollback、Pending 未发布、Active flags、cursor 保存、全部新行分类、source 保存和全部原备份行（含 audit/timestamps）精确不变均为 true；commit 后独立重读 preservation 再次通过。
- 首次 fixture 尝试因 source checker 将 fixture `updated_at` 误认为不可变而 fail closed，activation transaction 回滚。核对真实 `_write_classifications` 后仅允许该 synthetic fixture 的预期 classification timestamp 更新，原备份全行检查保持不变；旧 attempt 集群已删除，成功结果来自另一个 fresh restore。未绕过任何 app checks。
- S9 成功；只保留 9 个有效 0600 JSON（新增 `pending_activation.json`），data/socket/old_src/log 不存在。此前 D15 的四指纹及 `compare.json` 保留，仍为 `all_identical: true`。再次 R2 验证 source SHA256/size 不变。
- D12 测量及技术验证全部完成：分类 0.057s、停用 apply 0.248s、重新激活 apply 0.400s、Pending activation core 0.454s。原 acceptance 文本没有数值 threshold，仍不能代替 owner 的 latency 接受决定。
- 26 个 focused wrapper/fixture/privacy 测试通过，shell syntax、Python compile 和 diff whitespace 检查通过。无 Production/Plaid/cloud/push/merge/deploy 操作。
