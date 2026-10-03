# 自定义标签合并前核对

核对对象：feature/custom-labels `7180352`；M5 工作树
`~/code/pft-m5-remaining`、HEAD `6395882f97af1961c8031da118c04d2e882cd9ac`。
本次仅读取 M5 文件、写本分支报告，并使用本机合成数据库补验。
未合并、部署、访问 Production 或调用 Plaid。

**结论：暂不建议合并。** 标签功能自身验证通过，但当前 M5 cron fixture
不能满足新的启动检查，且备份恢复指纹缺少约束函数/触发器覆盖。
M5 适配提交及组合验收仍待完成；本报告不将通知等同于适配完成。

## 82 项跳过测试

R1 是交付前的全套 Python 运行：313 项发现、231 项成功、82 项跳过，
不是 313 项全部通过。其环境仅开启 `PFT_LABEL_SYNTHETIC_TEST=1`，
使用 `127.0.0.1:55449/pft_custom_labels_tests`、`PLAID_ENV=sandbox`。
82 项均由类级 `skipUnless` 跳过，统一原因为 `isolated PostgreSQL opt-in`，
没有测试失败后转为跳过，也没有缺少标签数据库或未执行标签用例的情况。

下面的模块名均在 `tests/`，环境开关表示 `PFT_<名称>_SYNTHETIC_TEST=1`。

| 分类 / 模块 | R1 跳过数 | 未开启开关 | 与改动关系 | 本次 R2 补验数 |
| --- | ---: | --- | --- | ---: |
| 分类覆盖 / test_category_overrides | 1 | CATEGORY | 间接：通用 init_db 和重新分类须兼容新 schema | 1 |
| 用户/消费者范围 / test_consumer_scope | 10 | CONSUMER | 间接：原用户隔离、旧迁移与 provenance，非新增标签约束的唯一证据 | 2 |
| 派生写入 / test_derivation_writes | 7 | SYNC | 间接：分类和 raw 写入经过新增 guard；批量 diff/full rewrite 应一致 | 1 |
| Dining 迁移 / test_dining_migration | 6 | CATEGORY | 间接：保留旧 DDL 回滚、休眠决定与财务汇总；标签功能不改 Dining | 2 |
| 加密备份/恢复 / test_m3_recovery | 2 | M3 | 直接集成：全库 dump 新表、恢复后的启动检查 | 2 |
| Jobs / test_m4_jobs | 20 | M4 | 迁移兼容间接相关；其余调度、重试和 owner 丢失语义未改 | 1 |
| 账单持久化 / test_statement_persistence | 13 | STATEMENT | 间接：导入/回滚、已有 override 与通用 schema 安装 | 2 |
| 同步服务 / test_sync_all | 23 | SYNC | 迁移/分类写入间接相关；网络重试、deadline、性能和发布语义未改 | 1 |
| 合计 | **82** | | | **12** |

[82 项完整测试 ID、原始 skip 原因及标签启用列表](evidence/custom-labels-2026-10-02/audit/skip-inventory.json)
由本次 discovery-only 核对生成，发现数仍为 313；它只证明加载/开关情况，
不冒充一次新的测试执行结果。

R2 仅补上述 12 项缺口，**12 成功、0 失败、0 跳过，5.421 秒**。
[逐项日志](evidence/custom-labels-2026-10-02/audit/gap-tests.log) 和
[结果/源码 hash](evidence/custom-labels-2026-10-02/audit/gap-results.json) 列出准确 ID。
旧测试硬编码端口 55439；为不触及其他 agent 的数据库，在 /tmp 复制测试，
仅将其端口断言改为本任务的 55449。应用源码与测试断言均未改；
该唯一 harness 差异及源码 SHA-256 已记录。外网 socket 与真实 Plaid client
在 harness 中禁止。剩余 70 项没有新增执行结果，不声称全套无跳过。

## 关键要求在哪次实际通过

以下标签用例属于 R1 的 **20 项数据库 + 7 项规则测试**，均非 skip。
已有证据引用 [原交付验证记录](CUSTOM_TRANSACTION_LABELS.md#verification-2026-10-02)，
不重复跑已覆盖的用例。R1 留存的是聚合结果，未留存逐项 verbose 日志；
本次通过源代码与 discovery 清单核对参与范围，明确区分它与 R2 的逐项日志。
下表测试名位于 `tests/test_transaction_labels.py`。

| 要求 | 实际通过运行 / 用例 | 验证内容 |
| --- | --- | --- |
| 标签迁移 | R1 `test_migration_idempotency_and_existing_row_preservation`、`test_custom_upgrade_preserves_legacy_decisions_and_totals` | 重建旧枚举 CHECK 后迁移两次；CHINA/MEMBERSHIP audit 行完全相同；月度及 membership 汇总相同 |
| 跨用户 DB 约束 | R1 `test_custom_db_rejects_cross_owner_identity_changes_reparent_and_archived_include`、`test_custom_provenance_may_move_within_same_owner` | 直接 SQL 拒绝跨 owner 关联、改 owner、跨用户 reparent；同用户移动允许 |
| API 用户隔离 | R1 `test_custom_names_colors_scope_and_concurrent_duplicates`、`test_scope_and_validation` | 他人标签不可读取/修改/筛选/应用，用户内重名拒绝 |
| 并发重名 | R1 `test_custom_names_colors_scope_and_concurrent_duplicates` | 并发 gear/GEAR：仅一个成功、另一个 409；Unicode casefold 与 SQL lower 唯一性另有覆盖 |
| 并发归档 | R1 `test_custom_archive_waits_for_inflight_include_and_blocks_following_include` | 归档等待在途 include 事务；已提交历史保留；后续 include 被拒绝 |
| 系统标签回归 | R1 `LabelRuleTests` 的 7 项，尤其 china vocabulary、membership 手动优先/clear、精确描述与卡费规则；另有数据库 `test_api_review_analytics_filter_and_financial_invariance`、`test_pending_manual_audit_noops_clear_and_classifier_survival` | 既有自动规则、优先级、分类后审计保留与财务不变 |
| 归档 restore | R1 `test_custom_rename_archive_remove_restore_preserve_audit_and_history` | restore 清除手动决定/保留审计、不恢复自定义关联；系统 CHINA 有效关联保留 |
| 既有服务迁移/恢复组合 | R2 的 12 项 | 分类、消费者、Dining、M4、statement、sync 迁移兼容；真实 api.backup 加密恢复与启动检查通过 |

原独立 dump/restore 验收 R0 已保存
[restore-results.json](evidence/custom-labels-2026-10-02/restore-results.json)：
15 表全部行一致、3 functions / 4 triggers 一致，月度/membership 汇总一致，
恢复后的实际 SQL guards 正常。R2 另补验的是 `api.backup` 的加密恢复路径，
不把本地 pg_dump 成功当作 M5 age/GitHub 全链路已通过。
浏览器、前端 68 项测试和构建沿用原证据，没有重跑或修改 UI。

## M5 责任与适配状态

M5 现有任务为 `01a0f8aa-4a5a-7130-87b0-f7d55a8e57c7`（Verify cloud integrations）。
此前已确认接手检查；本轮已发状态核对及具体缺口/证据。读取到的状态仍为
`waitingOnApproval`，尚无适配完成回复或新提交。此状态不是本分支测试受阻，
也不是本轮 automatic approval review 的拒绝。下列由 M5 修改的项目仍待其确认。

| 项目 | 当前可查代码/提交 | 负责人 | 状态 / 剩余事项 |
| --- | --- | --- | --- |
| 新表、稳定系统 IDs、FK、guards、迁移和 startup | feature `7180352` | custom-labels agent | 已实现；R1/R0/R2 验证通过 |
| 备份 payload 自动包含新表 | 全库 `api.backup`；M5 schema snapshot dump 基础提交 `e648e4e` | M5 runner / custom-labels 验证 | dump 没有固定 table allowlist，新表及 functions/triggers 自动包含；R0/R2 本地恢复通过，M5 age/release 路径组合验收待办 |
| 表/列/FK/index 动态指纹 | M5 `deploy/backup_runner/fingerprint.sql`，`e648e4e` | M5 agent | I1 实测新定义表进入指纹；这部分无需手工添加表名 |
| guard function/trigger 指纹 | 同上 | M5 agent | **未适配，无对应提交**。须覆盖函数定义/search_path 属性、trigger 定义和 enabled 状态；同步更新 runner SHA256SUMS/恢复工具所需 fixture |
| 自定义标签 backup fixture | `scripts/pft_m5_backup_fixture.py`，基础 `4beb749` | M5 agent | 仍只生成 MEMBERSHIP 手动决定；须有 active/archived 自定义定义、多标签历史及 restore/跨用户拒绝验收 |
| 固定 table 数 | `tests/test_m5_backup_age.py` 基础 `e648e4e`，最近相关文件提交 `4db0a84` | M5 agent | 当前断言已是 15，M5 模型定义为 14；feature 为 15。不能机械将所有 15 改成 16，应按最终 schema 和额外 ops 表核对实际计数，并跑 full-chain |
| cron schema fixture | `experiments/m5_cloud/cron_fixture.py`，`6395882` | M5 agent | **未适配，无对应提交**。CreateTable/CreateIndex 克隆不执行 metadata.after_create，缺 system seed / 3 functions / 4 triggers；需正确 schema/search_path 安装和角色权限 |
| 最终组合验收 | 两分支适配后的一致候选树 | 两个 owner；custom-labels 复核 | 待 M5 提交与集成 candidate，不要求先合并 main，可在独立候选 worktree 验收 |

I1 已用 feature 模型 + M5 `6395882` cron 生成器在隔离 schema 验证，
没有 merge 或修改双方代码：**system definitions=0、label guards=0，
启动被拒绝**；当前 M5 指纹有定义表、没有 function/trigger 记录。
[准确输出](evidence/custom-labels-2026-10-02/audit/m5-integration-results.json)。
这是预期的集成拒绝证据，不计为标签功能用例失败，也不计为集成通过。

必须在适配后的最终组合源码验收：

1. M5 age backup → decrypt → restore：新定义/关联/财务汇总一致，指纹包括
   3 函数、4 enabled guards；篡改函数或禁用 trigger 应产生 fingerprint 差异。
2. Populated fixture 包括 active/archived/custom/built-in；恢复后跨用户、归档
   include 直接 SQL 均拒绝，custom restore 清除且不重新建立关联。
3. Cron 私有 schema 种子与 guards 正确；真实 jobs/reader 角色可启动并拥有
   各自必要权限；guard search_path 固定到该 schema，不回落到 public 同名表。
4. 最终实际 table 数、固定断言、bundle/fixture、runner SHA256SUMS 一致，
   同时复核 M5 对 api/db 与模型的组合无遗漏。无需 Production 或真实 Plaid。

## 部署顺序（说明性计划，本轮不执行）

在上述合并门槛完成、另行获得部署授权后：

1. 固定一致的 migration/API/jobs/web/backup-runner 版本，核验目标数据库身份；
   先完成迁移前备份及匹配旧版本的恢复验证。进入维护窗口，暂停 API 写入、
   jobs/sync 和导入服务，避免迁移与写入竞争。
2. 用新版本的 schema-owner 配置显式运行 `python -m api.migrate_once`。
   正常服务启动不会自动迁移。该命令校验运行配置/数据库名并在事务中调用
   init_db/migrate_transaction_labels：创建表与索引、seed CHINA/MEMBERSHIP、
   将旧标签枚举 CHECK 换成 FK、安装 3 函数 / 4 guards。保留所有旧 audit 行。
3. 检查 validated FK、enabled guards、owner/schema/search_path、旧关联和财务
   汇总；按既有角色策略补新表的 SELECT 或标签写入权限。当前 API 身份继续
   用已有用户 helper，不临时实现 Auth 或改变用户范围。
4. 更新使用模型的 API 与 jobs 后端，先通过 verify_runtime_schema 和只读
   财务/registry smoke 检查；同步更新已适配的 M5 backup runner/fixture。
   旧 cloud fixture 必须先适配再启用，不得关闭 guards 绕过检查。
5. 后端正常后更新 web，再做单笔/批量/归档 smoke；最后恢复写入口和 jobs。
   备份恢复验收是新 runner 启用前的门槛，合并许可不等于部署许可。

## 回滚限制

- 未提供 down migration。创建 custom audit 后，旧枚举 CHECK 无法重新安装；
  删除定义表、去掉 guards、清除 custom overrides 不是无损回滚。
- 应用回退与 schema 回退必须分开判断。旧 web/API 不会管理 custom labels；
  即使旧二进制能够启动，也未验证完整向后运行兼容，不能直接当作安全回滚。
  尤其禁止运行旧迁移脚本重新添加标签枚举 CHECK。
- 需要回退时先冻结写入并保留当前全量备份；优先保留迁移后 schema 做修复前进。
  若必须恢复迁移前备份，在另一个隔离目标配套旧版本验证，再经单独授权切换；
  恢复旧点会丢失其后标签和其他财务写入，须先处理这段增量，不能默默覆盖。
- 无标签永久删除路径；archive/restore 不等于 undo migration。本轮没有执行
  任何上述部署或回滚动作。

## 后续本地适配

本报告是适配前的历史核对；固定 SHA 的后续适配结果见 [本地集成验收](CUSTOM_LABELS_M5_LOCAL_INTEGRATION.md)。
