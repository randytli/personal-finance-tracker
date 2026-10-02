# 恢复副本彩排命令清单（D15 + D12）— 2026-10-02

**状态：等待 owner 逐条批准。本文中的命令一条都还没有对真实备份执行过。**

目的：把最近一份 Production 备份恢复到一次性的临时集群，在副本上依次执行旧代码指纹、严格 preflight、迁移、新代码指纹，并测量预览和激活的耗时。全程**不连接 Production**（不连它的数据库，不执行 docker 命令），不调用 Plaid，用完删除集群。

所有步骤都由 `scripts/pft_lifecycle_restore_rehearsal.sh STEP` 执行，每一步就是下表中的一条命令。脚本内容就是审阅对象。

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
export PFT_REHEARSAL_OLD_COMMIT=<R2 输出的 application_commit>
```

开始前：`scripts/pft_lifecycle_restore_rehearsal.sh S0`（**[STATE]**，只创建配置的本地私有目录并验证路径、当前用户所有权和 0700 权限；路径必须为绝对、规范、非根且无符号链接的路径，直接父目录必须已存在且为目录，不能创建或修改父目录）。

## 命令清单

| 步骤 | 类别 | 做什么 | 读/写 | 停止条件 |
|---|---|---|---|---|
| S0 | **STATE** | 在已存在的直接父目录下只创建最终彩排目录（0700），验证路径和所有权；输出安全路径/状态 | 只写最终本地目录 | 父目录不存在或不是目录，路径、所有权或权限不符合要求 → 停 |
| R1 | READ | 按文件系统修改时间从新到旧列出最多 12 个 manifest（`filename`、`size`、UTC `modified_at`）；不读取内容、不自动选择 | 读备份目录元数据 | 候选不是普通文件或是符号链接 → 停 |
| R2 | READ | 校验 owner 选定的 `.dump` 和同目录同名 `.json`；输出 manifest 字段（时间、kind、size、sha256、schema_sha256、application_commit、format），`actual_size`、`actual_sha256`、`table_data_count` | 只读所选 manifest 和 dump，执行 `pg_restore -l` | sha256 或已记录的 size 不一致、字段/文件缺失、映射不明确、manifest 格式错误或 archive 不可读 → 非零退出并停 |
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
| S9 | **STATE** | 停止集群，删除 `data`、`sock`、`old_src` 和日志，只保留 `results/*.json`（0600） | 删除本地临时数据 | — |

收尾时，在 S9 之后由你决定 `results/` 的去留。如需删除，执行 `rm -rf -- "$PFT_REHEARSAL_DIR"`（**[STATE]**）。

## 预期与判定

- **R1/R2 备份合同**：由 owner 选择规范绝对路径 `$PFT_BACKUP_SOURCE_DIR/<stem>.dump`（不接受 `..` 或符号链接路径），manifest 必须为同目录的 `<stem>.json`；二者必须是普通文件且不能是符号链接，不使用 manifest 字段指定备用文件路径。R2 必需字段为 `created_at`、`kind`、`sha256`、`schema_sha256`、`application_commit`、`format`：`created_at` 必须为备份工具输出的 UTC `datetime.isoformat()` 格式（`+00:00`，可含六位微秒）；`kind` 必须为 daily/weekly/monthly/extra；两种 SHA256 必须为 64 位小写十六进制；`application_commit` 必须为运行指南中 `git rev-parse HEAD` 输出的完整 40 位小写 Git hash；`format` 必须为 `pg_dump-custom`。拒绝重复字段。`size` 如有记录必须为非负整数且与实际字节数一致；未记录时输出 `size: null`，仍验证 SHA256。R2 仅在所有校验及 archive inspection 成功后输出结果；不输出 archive listing 或错误中的原始内容。
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
