# M5 无人值守夜间工作交接 — 2026-10-02

分支：`m5-remaining-20261002`（从 `main` @ `47183eb` 创建；未 push，未合并，未改动 `main`）。

开始时间：2026-10-01 23:55 EDT；结束时间：2026-10-02 00:27 EDT（均为 `date` 实测）。五项任务全部完成，提前于 03:00 收尾。剩余的 M5 事项都需要云端执行或 owner 拍板，超出今晚的边界，所以没有自行扩大范围。

## 边界遵守情况

- 未访问本机 Production（未连接其数据库，未对 api/jobs/web/db 容器执行任何 docker 命令）。
- 未对 Supabase / Vercel 做任何操作（包括 MCP 读取），未调用 Plaid。只用 web 查阅官方文档。
- 未读取 `/tmp/pft-m5-cloud-private-20261001/`、`.env*` 或任何凭据文件。
- 数据库原型只用 scratchpad 下的一次性 PG16 集群（127.0.0.1，非默认端口），用完删除。
- **commit 说明**：记忆中记录过“owner 自己 commit”的偏好（2026-10-02），但今晚的指令明确要求每项完成后在新分支上 commit，因此按今晚指令在 `m5-remaining-20261002` 上 commit，未 push。

## 已完成

### 0. 盘点

- 产出：[docs/PFT_M5_REMAINING_INVENTORY_2026-10-02.md](PFT_M5_REMAINING_INVENTORY_2026-10-02.md)
- 结论：SERVERLESS_GO 的放行标准是计划 §12 的 8 项（G1–G8），每项都需要正面证据，未知不算通过。目前 G6（Auth）、G7（独立备份）尚未开始，G2（catch-up/重试场景）、G4（取消后终态缺口）、G5（暂停/配额）仍有未知。剩余事项共 21 条（R1–R21）。
- 与今晚任务清单的出入（以文档为准）：
  1. 文档要求但今晚清单没有的：云端 catch-up/重试/部分失败的余量测试（R8）、应用 deadline 取值（R9）、**取消后 durable 状态停在 `running` 的缺口（R10）**、硬终止/不确定提交（R11）、O(n²) 分类 CPU（R13）、多实例连接预算（R14）、`api.db` 全局 engine 懒加载（R17）、$0 账单证据（R19）、M5 一次性资源的清理（R21）。这些大多需要云端执行或 owner 看控制台，今晚边界不允许，列入“待决”。
  2. 任务 3 只写设计，关不掉 G6：计划要求在合成项目上实测登录/刷新/登出和反向测试。
  3. 任务 4 属于 M8，M5 不能授权迁移；草案标注为不可执行。
  4. 任务 1 的本地原型关不掉 G7：还需要真实的独立存储上传/回读/下载，以及 PG17 托管库的恢复；存储选型需要 owner 批准（B2 闸门明确关闭）。
  5. 计划 §16.1 提议保留 7 个日备份；现有本地是 7 日 + 4 周 + 3 月。按“不少于现有本地覆盖”的要求，设计沿用三层保留。
- commit：`02a3587`

### 1. 独立加密备份与恢复

- 产出：[设计文档](PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md)、`scripts/pft_m5_backup_drill.py`（PFTENC3 原型，**已于 2026-10-02 删除，由 age 版本替代**，见下面第 6 项）、`scripts/pft_m5_backup_fixture.py`（合成数据，15 张表全部有数据）、`tests/test_m5_backup_drill.py`（12 个测试）、[实测结果](evidence/m5-2026-10-02/backup-drill.json)。
- 本地原型链路：同一快照内算指纹 + `pg_dump --snapshot`，然后用 X25519 公钥加密（运行端不持有解密密钥），再上传到本地目录模拟的存储并回读校验哈希，按 GFS 7/4/3 保留，最后下载、认证解密、恢复到全新库并做指纹比对。**实测**（PG16 本地回环，单次）：
  - 2,610 行：备份 0.20 s，恢复加校验 0.36 s；
  - 35,600 行：归档 3.3 MB，备份 1.5 s，恢复加校验 1.8 s；
  - 指纹全部一致。
- 测试：12 个全部通过，其中 3 个用数据库；`test_m3_recovery` 回归 2 个也通过。测试证明链路不是空转：
  - 备份后的写入不会出现在恢复结果里；
  - 改一行、删一个索引都会被比对检出；
  - 错误密钥、篡改、截断都被拒，且不留明文；
  - 出现未选中的应用 schema 时直接失败。
  - 密钥只在测试中临时生成，存在临时目录里，用完删除。
- 三个问题的结论（均有官方出处，查阅日期 2026-10-02）：
  1. Supabase Free 没有任何例行备份，也没有 PITR（官方定价页写 "Backups: Not included"）。暂停的项目可以在 1 年内恢复。
  2. 仍然需要独立备份：官方文档写明删除项目会“永久删除所有数据，包括备份”，官方也建议 Free 用户自己做异地备份。
  3. 最坏情况（项目被删）：只能恢复到最后一次通过回读校验的独立备份，名义 RPO ≤ 24 h。之后的手工编辑会丢失；Plaid 来源的数据大概率可以用旧 cursor 重新拉取（推测，未核实）。项目被暂停则不丢数据。
- 遇到的问题：
  - 恢复时新库已经自带 `public` schema，导致冲突。改为用 `pg_restore -L` 跳过 dump 里的 `CREATE SCHEMA public`，不做 `DROP SCHEMA public`（计划 §15.3 禁止对托管项目这样做）。
  - PG 恢复后会把 CHECK 约束里的 varchar 数组写法改成等价形式。只对这一种形式做规范化，并加测试证明真正的改动仍会被检出。

- commit：`4beb749`

### 2. 定时触发（Cron）

- 产出：[设计文档](PFT_M5_CRON_TRIGGER_DESIGN_2026-10-02.md)、`api/trigger_auth.py`（未挂到 `api/main.py`，Windows runtime 不受影响）、`experiments/m5_cloud/trigger_cron.sql.template`（SQL 签名函数、nonce 表，schedule 只以注释形式给出）、`tests/test_m5_trigger_auth.py`（10 个测试）。
- 结论：
  - **Vercel Hobby 不可用**（官方原文：每天一次、±59 分钟、失败不重试、尽力投递且可能重复）。15 分钟、1 小时、6 小时的重试会退化成“第二天”，手动同步最多要等 24 h。
  - **建议用 Supabase Cron**：每 5 分钟一次，通过 pg_net 直接调用受保护的 Python jobs 端点。`timeout_milliseconds` 不小于 300 s；pg_net 默认 2 s，上限未核实。完成与否以 durable 状态为准，不看 net 响应。另设一个每日清理 `cron.job_run_details` 的任务（官方写明它永不自动清理）。
  - 和现有语义的对应：24 h 变成 24 h 至 24 h 5 min；15 分钟重试变成 15–20 分钟；手动同步从 ≤60 s 变成 ≤5 分钟。
- 暂停规则（官方原文）：Free 项目“1 周不活跃”就会暂停；不活跃的定义是“没有足够的用户数据库活动”；“每天几次用户请求通常就够”；官方给出的防止办法是升级 Pro；暂停后 1 年内可以恢复。
  - pg_cron 自身的活动算不算，文档没说，**未核实**。
  - 真实同步会从 Vercel 经 Supavisor 回连数据库，属于真实的应用流量，大概率算活动（推测）。
  - 按计划，不加任何保活 ping。
  - 暂停后 cron 也会随之停止，需要你手动恢复。
- 鉴权：
  - HMAC-SHA256 签名覆盖 audience、key id、时间戳（±300 s）、单次 nonce、方法、固定路径和规范化 body。
  - 校验在任何 DB 工作之前完成；nonce 在独立事务中提交，重放返回 409，伪造请求连 nonce 表都碰不到。
  - 可以同时接受两个 key id，用于轮换。
  - 与 advisory lock 的配合已实测：两个并发的合法投递，第二个返回 `busy`，只跑一次 sync；锁释放后可以再次执行。
  - SQL 签名（pgcrypto）与 Python 校验一致，已在本地实测。
- 测试：触发器 10 个，加上回归的 scheduler draft 和 M4 jobs，共 33 个全部通过。

- commit：`e54b25c`

### 3. 认证（Auth，仅设计）

- 产出：[设计文档](PFT_M5_AUTH_DESIGN_2026-10-02.md)。没有写代码。
- 结论：
  - **禁止注册**：关闭 "Allow new users to sign up"、匿名登录、手动关联，也不启用任何社交登录。只预建一个 owner 用户，再在 FastAPI 侧固定 `sub == PFT_OWNER_AUTH_SUB` 作为兜底。主体映射到现有的 `PLAID_PILOT_USER_ID`，历史数据不受影响。
  - **MFA**：Free 自带 TOTP（官方定价页 "Basic Multi-Factor Auth: Included"），要求 `aal2`。Free 没有泄露密码检测。
  - **Next.js**：`getClaims()` 负责保护页面和刷新 token；服务器端绝不信任 `getSession()`（官方原文）。现有的 4 组 `/api/pft` rewrite 改为服务器路由处理器，把 Bearer 转发到固定的上游。
  - **FastAPI**：只从配置的 JWKS 取公钥，只接受 ES256，校验 iss、`aud=authenticated`、exp、iat、`sub`、`aal2`、`is_anonymous=false`；遇到未知 kid 时最多 60 s 刷新一次，失败即拒绝。
  - **RLS**：完全关闭 Data API（官方：关闭后“无论 grants 或 RLS，REST 端点都不响应”）。再加一层兜底：所有表启用 RLS，只给服务端角色写策略，`anon`/`authenticated` 没有任何权限。
  - **数据库角色**：reader 只读，且看不到 `items.access_token`；writer 只能写手工覆盖类表；jobs 负责同步；backup 只读全表；migrator 只在运维机上使用。
  - **与 Tailscale 相比**：对“已经能连上应用的人”更安全（每个请求都有真正的认证，加上 MFA 和最小权限）；但暴露面更大（公网可达，秘密分散在三家服务商，任何认证或路由 bug 都直接暴露在公网）。直连 API 的反向测试仍然是上线前提。

- commit：`fe68845`

### 4. 切换与回滚方案（草案）

- 产出：[docs/PFT_M8A_SUPABASE_CUTOVER_DRAFT_2026-10-02.md](PFT_M8A_SUPABASE_CUTOVER_DRAFT_2026-10-02.md)。文件明确标注为“草案，不可执行”，没有执行其中任何步骤。
- 内容：
  - 前置条件 C1–C8：GO、identity sentinel、TLS 指纹工具、目标库角色与 RLS、PG17 客户端和恢复环境、独立备份、remote Compose、执行窗口。
  - 步骤 0–7，每步都标注了 [READ-ONLY]/[LOCAL]/[STATE]：冻结写入、F1 指纹、dump、F2=F1、在隔离的 PG17 上恢复并核对 F_iso=F1、导入 Supabase 后 F3=F1、只读验证后 F4=F3、目标库的首份独立备份恢复后 F_bk=F3、权威移交。
  - 两种回滚：写入目标之前，按固定的 image pin 重启本地，并核对 F1；写入目标之后，先冻结、先备份，优先在原地修复；反向迁移需要另行批准，并且需要 PG17 本地环境。
  - M8b/c/d 只列出了边界。
- 注意：切换属于 M8，M5 不能授权迁移；文档中写明了这一点。

- commit：`9398c20`

### 5. PLAID_PILOT_USER_ID 测试隔离

- 复现（实测）：同一个一次性集群上全套 326 个测试，环境干净时全部通过；shell 中带有 `PLAID_PILOT_USER_ID=leaked-shell-user` 时，`tests.test_category_overrides.CategoryDatabaseTests` 报 1 个错误。原因是测试写死了 Item 的 `user_id='local-sandbox-user'`，而 review 路由按环境变量限定用户范围。
- 修复（只改测试）：该测试类在 `setUp` 中用 `patch.dict` 固定 `PLAID_PILOT_USER_ID`，并用同一个常量创建 Item，和 `test_consumer_scope`、`test_transaction_labels` 的做法一致。
- 验证：全套 326 个测试（含 7 个原有的 PG opt-in 和今晚新增的 2 个），在三种设置下都通过，0 跳过：变量未设置、`leaked-shell-user`、`local-sandbox-user`。
- 已用泄露值实测全套：除这一处外，没有其他测试依赖 `PLAID_PILOT_USER_ID`。其他环境变量（例如 `PFT_STRICT_LOCAL_HTTP`）是否也会泄露进测试，未排查。

### 6. age 备份 runner、GitHub release 存储适配器和恢复工具（2026-10-02 白天，owner 指示）

- **纠正一处说法**：Windows 本地备份从来不是 PFTENC3。它们是普通的 `pg_dump -Fc` 加 JSON manifest（`api/backup.py`），以及可选的外部加密副本 **PFTENC2**（`api/backup_crypto.py`，密码 + scrypt）。PFTENC3 只是昨晚的原型，已经从分支上删除。按要求，Windows 的这两种格式在 M8c 之前保持不变；恢复工具支持 age、PFTENC2 和普通本地 dump 三种格式。
- 产出：
  - `deploy/backup_runner/`（README、workflow 模板 `pft-backup.yml`、runner、存储适配器、`snapshot_dump.sql`、`fingerprint.sql`、`SHA256SUMS`）
  - `scripts/pft_backup_restore.py`（多格式恢复工具）
  - [不依赖 PFT 代码的恢复说明](PFT_BACKUP_RESTORE_RUNBOOK.md)
  - 更新后的[备份设计](PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md) §4.2–§8：age、密钥保管、丢失处理、P1-3 和 P1-5、过渡期
  - [实测结果](evidence/m5-2026-10-02/backup-age-drill.json)
- 要点：
  - **age v1.3.2 固定版本**。官方发布页上给出的 SHA-256 已固定在 workflow 里，下载后先校验再使用；我也在本地下载并重新计算过，一致。age 的发布没有单独的 checksums 文件，另附 Sigsum `.proof` 文件，校验它属于可选的额外加固，没有做。
  - **两个接收方**：daily 和 emergency 两个 X25519 公钥，少于 2 个就拒绝运行。任何一把私钥都能单独解开所有备份（已实测）。
  - **workflow 模板**放在 `deploy/backup_runner/`，故意不放进 `.github/workflows`，所以在本仓库里不会运行。三项都固定：`actions/checkout` 固定到 commit SHA；PG17.11 客户端镜像固定到 digest；runner 文件用 `SHA256SUMS` 校验。runner 只用标准库，不需要 pip 安装。
  - **GitHub 存储**：先建 draft，上传后逐个回读并比对 SHA-256，全部通过才发布；token 不会随重定向发到存储主机。
  - **快照一致性**：用测试注入一次“导出快照之后、pg_dump 之前”提交的写入，它既不在 dump 里也不在指纹里；去掉 `--snapshot` 的变异版本会让这个测试失败。
- 测试：`tests/test_m5_backup_age.py` 共 20 个，全部通过（含后来加的 staging 测试）。
- **备份仓库**：`randytli/pft-backups`，由你在 2026-10-02 创建，private，已有初始 README。匿名访问 API 返回 404，而该用户本身存在，说明仓库确实不公开（实测）。`deploy/backup_runner/stage_backup_repo.py` 会把应放进该仓库的文件按目录排好，并校验 `SHA256SUMS`，但它不会运行 git，也不会 push。安装顺序见 `deploy/backup_runner/README.md`：密钥 → 备份角色、variables 和 secret → CA 证书 → 暂存、审阅、push → 手动触发首次运行并在另一台机器上恢复 → 恢复成功后再启用每日定时。所有密钥都在测试中临时生成，用完删除。
- **本地没测到的部分**：真实的 docker 运行 PG17 镜像（测试里用 `env` 代替这层包装）、真实的 GitHub API（测试用本地假 API）、到 Supabase 的 verify-full TLS、`--snapshot` 能否穿过 Supavisor。这些都要等你批准的真实运行来验证。

### 7. 已执行的批准（2026-10-02 白天）

owner 说明“密钥稍后再做，其余批准”。据此执行了以下操作，只涉及 M5 合成项目和本地文件：
- **Supabase（只在合成项目 `acyghoemtdrilsdszolq` 上）**：
  - 先只读确认项目身份：`pft-m5-synthetic-20261001`，PG 17.11，ACTIVE_HEALTHY。
  - **核实了 `PROVIDER_SCHEMAS`**：项目中实际存在的服务商 schema 都在列表里；非服务商 schema 只有 3 个 `pft_m5_*`，另有一个空的 `public`。
  - 通过 migration `m5_backup_role` 创建了只读角色 `pft_backup`：
    - **暂时不设密码**（不能登录认证），等密钥就绪后再设，避免过早生成凭据；
    - 只有 31 张表的 SELECT，没有任何其他表权限；`default_transaction_read_only=on`；连接上限 2；
    - 看不到 `auth`，不能 CREATE；
    - security advisor 没有任何告警。
  - 只读确认 `postgres` 角色具备 CREATEROLE 和 BYPASSRLS（见下面的新发现）。
- **CA 证书**：已核对指纹 `807025AD…CAFA`（Supabase Root 2021 CA，2031-04-26 到期，文件中没有私钥），复制为 `deploy/backup_runner/supabase-ca.crt`。staging 脚本会再校验一次指纹，不一致就什么都不复制。
- **workflow**：要备份的 schema 改由仓库变量 `PFT_BACKUP_SCHEMAS` 指定（合成项目上是 `pft_m5_bench_2610 pft_m5_bench_35600 pft_m5_probe public`）。
- **P2-1 到 P2-3**：按建议，owner 已确认（2026-10-02 下午再次确认）。**P3-1 到 P3-4、P4-1、P4-2**：owner 审阅[决策清单](#决策清单p3-与-p4owner-已批准)后，于 2026-10-02 全部批准选项 A（详见清单中各项的“决定”）。这项批准本身**不授权**任何 Production 迁移或部署。
- **新发现**：生产环境按 Auth 设计会给所有表启用 RLS 兜底，`pg_dump` 遇到受 RLS 保护的表会直接报错（这是 fail-closed，不会静默备份不全），所以生产环境的 `pft_backup` 需要 BYPASSRLS。不能用 `--enable-row-security`，否则 dump 和指纹会在同一份“不完整”的数据上互相印证。已写入备份设计 §7 和 Auth 设计 §7。
- **没有做的**：
  - 没有 push 到 `randytli/pft-backups`：`gh` 没有登录，而且按安装顺序，密钥和 recipients 就绪之前推送 workflow，会导致每天定时失败；
  - 没有设置密码或 secret；
  - 没有运行 workflow；
  - 没有合并或 push 本分支，因为“是否合并或 push”是一个问题而不是批准，需要你明确说一声。

### 8. 工作目录、权限规则和 AGENTS.md（2026-10-02 下午）

- **工作目录**：
  - 主目录 `~/code/personal-finance-tracker` 已切回 `main`（`47183eb`，工作区干净）。
  - 本分支的工作移到独立的 worktree `~/code/pft-m5-remaining`。
  - 6a 那个 agent 在 `~/code/pft-institution-lifecycle` 工作（owner 已确认）。
- **push**：`git push -u origin m5-remaining-20261002` 被权限分类器拒绝，没有执行，也没有用其他方式绕过。你可以自己运行：`git -C ~/code/pft-m5-remaining push -u origin m5-remaining-20261002`。push 时，本地 `main` 上还没 push 的 3 个 commit 会作为本分支的祖先一起上传，但 `origin/main` 不会移动。
- **用户级权限规则**（`~/.claude/settings.json`，owner 审阅后写入；原文件备份在 `~/.claude/settings.json.bak-20261002-before-permissions`）：
  - deny 71 条、ask 54 条、allow 20 条。
  - 用官方发布的 jq 1.8.2 校验通过（下载后核对了 checksum）：JSON 合法，原有设置都保留，没有重复规则。
  - 写入后实测生效：读取 `*.key.age` 被拒；被 deny 的 Supabase MCP 工具也从会话里消失了。
  - 局限：
    - `Read`/`Edit` 规则只约束 Claude 自己的文件工具，管不到 Bash；
    - `Bash(...)` 规则是按命令文本前缀匹配，换一种写法就能绕开；
    - 只对 Claude Code 生效，不影响 Codex。

    要真正的硬边界，需要另行启用 sandbox（建议作为单独一步决定）。
  - 这批规则禁止 agent 修改 settings 文件，以后要改只能由你手动修改。
- **AGENTS.md**：新增“Working directories”一节：主目录只放 `main`，每个 agent 用自己的 worktree，不在别人的 worktree 里切分支、commit 或 stash，开工前先确认目录。**这条改动目前只在本分支上**，要合入 `main` 后其他 agent 才看得到。如果想更早生效，可以单独把这一节提交到 `main`（需要你决定，并在你自己的 worktree 或主目录里操作）。

## 2026-10-02 晚至 10-03 凌晨：M5 收尾进度（无人值守，截止 02:00 EDT）

分支 `m5-remaining-20261002`，均未 push。详细数字见 [Cron 验收记录](PFT_M5_CRON_ACCEPTANCE_2026-10-02.md)。

- **第一步（R10 恢复）**：`4db0a84`，全量 340 通过 / 9 跳过（本机无 age 二进制）。
- **pooler 锁实验 + 防护**：`e24f883`（同一 backend 已持有时拒绝重入；jobs 角色 idle 超时 330 s）。
- **cron 链路**：`6395882`、`97c8ba3`；preview `dpl_S8nSP25gk85ZQ2zPdxiUiGNSXqgj`。
- **已完成场景**（[M]）：冒烟；鉴权反向 8 例（全部按预期）；S3 多页 catch-up（10,000 行，65.7 s，真实 cron）；S4 重试 + S5 部分失败（真实 cron，partial，15 min 退避）；S8 响应丢失（pg_net 5 s 超时，函数照常完成并发布）；**S6 截止时间**（22:00 EDT 起；failed/run_deadline，209.9 s，未发布，余量 89.4 s）。
- **常驻 cron**：owner 21:59 EDT 指示后立即 `cron.unschedule('pft-m5-tick')` 和 `pft-m5-history-prune`，`cron.job` 已确认为空。真实 cron 共触发 2 次（01:50、01:55 UTC）。之后每个场景由 agent 主动 `pft_ops.dispatch_tick` 触发；场景期间用每秒一次的 `pft-m5-sampler`（只写 `pft_ops.m5_samples`，不投递），场景结束立即 unschedule。
- **约束变化**：owner 指示今晚不读取私有凭据目录，因此停用本地 `cron_observer` / `cron_evidence` / `cron_controller`（都需读 jobs 密码或秘密），改为 MCP SQL 取证；后台观察器已停止，无残留进程。

## 待决（需要 owner 拍板或批准）

### 2026-10-02 晚：M5 收尾（R10 恢复 + 合成云端验收）新增的待决

按 owner 指示（“遇到超出范围的操作、设计决定或需要本人处理的凭据操作，不等待，记在这里，继续下一项”），以下事项 agent 没有执行：

1. **合成项目 Auth 控制台设置（owner，控制台）**：项目 `acyghoemtdrilsdszolq` 当前 `disable_signup=false`（注册开放，2026-10-03 01:47 UTC 只读 `/auth/v1/settings` 实测）。匿名登录已关、无社交登录、邮件确认已开。需要：关闭 “Allow new users to sign up”；在 Authentication → Users 手工建一个合成 owner 用户（勾选 auto-confirm）；确认 MFA 里 TOTP 为启用。MCP 没有 Auth 配置接口，也不应绕过 CLI 调管理 API。
2. **Auth 流程实测（owner，本人终端，不经 agent）**：用独立 venv 运行 `experiments/m5_cloud/auth_owner_flow.py`（脚本拒绝在非 TTY 下运行，TOTP 秘密只写 `/dev/tty`，证据只含状态码）。顺序：`negatives`（注册关闭后才会测注册/匿名）→ `flow`（登录、aal1 被拒、TOTP 注册与验证、aal2 通过、刷新、登出）→ `recover`（需要在该终端设 `PFT_M5_SECRET_KEY`，删 TOTP 因子、重设密码）→ 再 `flow` 一次重新绑定 TOTP。命令：
   `cd ~/code/pft-m5-remaining && /home/randyli/.claude/jobs/fd07ef9c/tmp/authvenv/bin/python -m experiments.m5_cloud.auth_owner_flow <negatives|flow|recover> --out docs/evidence/m5-2026-10-02/cloud/auth-<cmd>.json`
   （该 venv 在 job 删除时会被清理；没有它时：`python3 -m venv /tmp/x && /tmp/x/bin/pip install 'PyJWT[crypto]' cryptography==41.0.7`。）
3. **Vercel 清理（owner）**：`vercel env rm`、`vercel rm` 被权限规则禁止，agent 不做。需要删除：jobs 项目 preview 环境变量 `M5_CRON_ENABLED`、`M5_TRIGGER_AUDIENCE`、`M5_CRON_DATASET_ID`、`M5_CRON_DATABASE_URL`、`M5_TRIGGER_KEYS`；本次部署的 preview（清单见验收文档）；jobs 项目上的两条 automation bypass（本次一条、2026-10-01 一条），在 Project Settings → Deployment Protection 撤销。旧实验的 `DATABASE_URL` 内的 `pft_m5_jobs` 密码已在本次轮换，旧值不再可用。
4. **P2-3 偏离（设计决定）**：本次合成验收用 preview + Vault 中的 bypass 头（owner 当场选择），不是 P2-3 批准的“production 目标 + 仅 HMAC”。production 目标路径（以及“确认 production 目标不暴露其他路由”）仍需在 M7 验证。
5. **本机工具**：为让 ask/deny 规则对 `vercel` 生效，全局安装了 Vercel CLI 62.1.0（nvm 全局），可用 `npm uninstall -g vercel` 撤销。

### 任务 1：备份

- **P1-1 存储选择 — 已拍板（2026-10-02，owner 同意采用 GitHub 私有仓库）**。原建议：主存储用一个专用的 GitHub 私有仓库，每份备份是一个 release asset。理由：
  - 不需要绑卡；
  - Actions 在没有付款方式时超额会被直接阻止（官方原文）；
  - releases 官方写明“总大小与带宽不限”；
  - 独立于 Supabase 和 Vercel。

  风险：GitHub AUP 保留对“过度占用”的处置权；同一个 token 既能上传也能删除。B2 仍是备选，但它的闸门由你关闭，我没有动它。R2 和 GCS 要求结账流程或 billing account，又没有硬上限，所以不建议。
- **P1-2 备份在哪里跑 — 已拍板（2026-10-02，owner 同意采用 GitHub Actions）**。owner 接受“只读的第二个调度器”作为计划 §12.4 的明确例外。适用范围：只读导出，不拿 advisory lock，不做金融写入，不调用 Plaid，不持有 Fernet key，唯一的写入是一行 `backup_runs` 记录。R3 因此在设计上解决：云端 tick 使用 `backup_fn=None`，Cron 只分派 `tick`。原建议：用 GitHub Actions 定时 workflow，使用固定 digest 的 `postgres:17.11` 镜像，只连只读备份角色。好处是和 `tick` 及 Vercel 的 300 s 完全解耦，消除 R3（备份先于同步、取消后线程仍在跑）。代价是多出一个“只读的第二个调度器”，与计划“一个调度器”的措辞有冲突，需要你接受。如果不接受，就改为由 Supabase Cron 分派一个独立的 Vercel 备份 job kind。
- **P1-3 第二份副本 — 已拍板（2026-10-02，按建议执行）**：每月一次，另在计划内的迁移或切换前加一次。手动下载最新一份的 3 个 `.age` 文件，放到 Google Drive 或离线介质，至少保留最近 3 份。原建议：你每周或每月手动下载最新一份，放到 Google Drive 或离线介质，用来防 GitHub 账号丢失。不给自动化任何 Drive 凭据。
- **P1-4 加密格式 — 已拍板（2026-10-02）：采用 age（X25519 公钥加密），不用 PFTENC3。** 原文：PFTENC3 由经过审查的原语组合而成，但格式是自定义的。建议在 M6 实现前请人独立审查一次；也可以改用标准的 `age`，代价是每个恢复环境都要多一个二进制。
- **P1-5 备份频率 — 已拍板（2026-10-02，按建议执行）**：每天 08:23 UTC 一次，另在每次迁移、切换或 schema 变更前手动触发一次。原建议：每日一次，外加每次迁移、切换或 schema 变更前手动补一次。每日两次可以把 RPO 减半，成本可以忽略。
- **需要批准才能执行的操作**：
  - 创建备份仓库和 workflow；
  - 你离线生成真实密钥对，只把公钥交给 workflow；
  - 在 M5 合成项目上创建只读备份角色；
  - 在合成项目上跑一次真实的“PG17 dump → 上传 → 换机下载 → 恢复 → 指纹比对”；
  - 核实 `PROVIDER_SCHEMAS` 列表（目前未核实，原型遇到未知 schema 会直接失败）。

### 任务 2：Cron

- **P2-1 节拍 — 已确认（owner，2026-10-02）**。建议：先用 5 分钟（每月 8,640 次，计划给的起点）。1 分钟（每月 43,200 次）能恢复今天 ≤60 s 的手动延迟，但 CPU 和连接成本未测，等云端实测后再决定。
- **P2-2 接受“可能被暂停” — 已确认（owner，2026-10-02）**。官方给出的防止办法是付费升级，计划又禁止保活流量。建议接受：真实的同步流量本身大概率能维持活跃（推测）。一旦暂停，靠官方的警告邮件和 PFT 的过期告警发现，然后手动恢复。
- **P2-3 pg_net 怎样穿过 Vercel 部署保护 — 已确认（owner，2026-10-02，选 (a)：production 目标 + HMAC，前提是在部署前确认 production 目标不暴露其他路由）**。可选：(a) 部署到不受保护的 production 目标，只靠 HMAC 保护；(b) 使用 automation bypass 头，多一个存在 Vault 里的秘密。建议 (a) 加 HMAC，因为 bypass 头只是静态秘密，比 HMAC 弱。这需要你确认 production 目标不暴露任何其他路由。
- **需要批准的操作**：在 M5 合成项目上启用 pg_cron、pg_net 和 Vault，部署带校验的 jobs preview，跑一次真实的节拍、重复投递和超时测试（见设计 §5）。

### 任务 3：Auth — **P3-1 到 P3-4 已批准（owner，2026-10-02，均为 A）**

具体内容见下面决策清单中各项的“决定”。

- **需要批准的操作（仅限合成项目，属于 M6/M7；本次批准不包括这些）**：建 owner 用户并关闭注册、启用 TOTP、迁移到非对称签名密钥、关闭 Data API、建 reader/writer/jobs 角色，然后跑反向测试矩阵。

### 任务 4：切换 — **P4-1、P4-2 已批准（owner，2026-10-02，均为 A）**

见下面的决策清单。批准的是方案选择，不授权执行任何 Production 切换步骤。

## 决策清单：P3 与 P4（owner 已批准）

每项依次写：决定、问题、可选方案、建议、理由、选错的代价。“推测”表示没有实测或文档依据。6 项都在 2026-10-02 由 owner 批准为选项 A；这项批准不授权 Production 迁移或部署。

### P3-1 浏览器会话模型

**决定（owner 已批准，2026-10-02）：A。** 使用官方 `@supabase/ssr` 的 cookie 会话加 Next.js 服务器路由和代理，不做完整 BFF。Next.js 的 `getClaims()` 只是纵深防御；FastAPI 必须独立校验转发过来的 bearer JWT，以及 owner 和 aal2 声明。


- **问题**：登录后，浏览器怎样持有和刷新会话，金融请求怎样到达 FastAPI。
- **可选方案**：
  - **A** — Supabase SDK 把会话存在 cookie 里（JS 可读），Next.js 服务器路由用 `getClaims()` 校验，再带上 Bearer 转发到固定的 FastAPI。
  - **B** — 完整 BFF：浏览器只持有一个 HttpOnly 的不透明 cookie；refresh token 加密后存在服务器端的会话表里；另需 CSRF token 和串行化的刷新。
  - **C** — 浏览器直接持 Bearer 调用 FastAPI（不经 Next.js 代理，需要 CORS）。
- **建议**：A。
- **理由**：
  - 单用户、强制 TOTP、短 JWT。
  - B 只能防 XSS 偷 token，防不了 XSS 冒用当前会话，却要多写会话表、加密密钥、CSRF、刷新竞态处理和撤销逻辑，这些都是安全关键代码。
  - C 让 FastAPI 直接面对浏览器，跨域和缓存面更大。
  - 计划允许在明确接受 XSS 取舍后使用 A。
- **选错的代价**：
  - 选了 A 却发生 XSS 或依赖被投毒：攻击者能拿走 refresh token，在会话被撤销前一直冒用；需要发现之后立即撤销会话并轮换密码。
  - 选了 B 但实现有 bug：会话固定、CSRF 或刷新竞态，而且 M6 要多做一个主要模块。
  - A 和 B 之间可以后期互换（FastAPI 侧不变），可逆性中等。

### P3-2 FastAPI 的 JWT 校验库

**决定（owner 已批准，2026-10-02）：A。** 使用 PyJWT 加 `PyJWKClient`：严格校验算法、issuer、audience、JWKS 来源和各项声明，并配齐反向测试。


- **问题**：Python 端用什么库校验 Supabase 签发的 JWT。
- **可选方案**：
  - **A** — PyJWT 加 `PyJWKClient`；
  - **B** — python-jose；
  - **C** — Authlib；
  - **D** — 直接用已固定版本的 `cryptography` 手写。
- **建议**：A。
- **理由**：
  - API 小，支持 ES256 和 JWKS 缓存，符合计划“使用维护中的库”的要求。
  - D 是自己写密码学协议，正是计划禁止的做法。
  - B 和 C 的当前维护状态我没有核实（推测 A 更稳妥）。
- **选错的代价**：库本身有漏洞或用法错误，可能导致伪造 token 被接受，也就是任何人都能读取财务数据。缓解办法：
  - 固定版本；
  - 只允许 ES256；
  - 只从配置的 JWKS 地址取公钥；
  - 用反向测试矩阵覆盖。

  校验逻辑封装在一个模块里，换库的成本低。

### P3-3 owner 账号恢复

**决定（owner 已批准，2026-10-02）：A。** 在可信机器上手动走 Supabase admin 恢复路径。admin secret / service-role 能力**绝不**暴露给浏览器或普通应用运行时。管理员删除 MFA 因子的能力已确认支持（见下面的“选错的代价”），所以重建 Auth 用户不再是常规的后备方案。


- **问题**：忘记密码或丢失 TOTP 时，怎样在不付费的前提下恢复登录。
- **可选方案**：
  - **A** — 无邮件路径：登录 Supabase 控制台（控制台账号自带 MFA），在可信机器上用 secret key 调用 `auth.admin.updateUserById` 重设密码。官方示例已核实。
  - **B** — 配置一个免费的自定义 SMTP，走邮件找回。
  - **C** — 依赖默认 SMTP（只发给团队成员，每小时 2 封，尽力投递）。
- **建议**：A；B 可以作为以后的补充。
- **理由**：A 不依赖任何邮件服务，也不增加新的第三方凭据；C 官方明确说不适合生产。
- **选错的代价**：
  - A 把恢复能力集中在 Supabase 控制台账号上。如果控制台账号的 MFA 也丢了，应用和数据库会同时失控，只能找 Supabase 支持。
  - TOTP 丢失时：管理员可以用 [`auth.admin.mfa.deleteFactor`](https://supabase.com/docs/reference/javascript/auth-admin-mfa-deletefactor)（参数 `id` 和 `userId`）删除这个因子。官方说明：如果删除的是已验证的因子，会让该用户的所有活跃会话下线。查阅日期 2026-10-02，直接打开页面返回 404，内容来自官方文档的搜索索引；owner 也确认这一能力受支持。之后重新登录并重新绑定 TOTP。因此重建 Auth 用户（并更新 `PFT_OWNER_AUTH_SUB`）不再是常规后备，只留给极端情况。
  - 选 B 多一个 SMTP 凭据要保护。

### P3-4 aal2（MFA）的强制范围

**决定（owner 已批准，2026-10-02）：A。** 所有金融路由（读和写）都要求 aal2。最小的非金融健康探针沿用各自单独定义的策略。


- **问题**：哪些请求必须完成第二因素认证（`aal2`）。
- **可选方案**：
  - **A** — 所有金融路由（读和写）；
  - **B** — 只有写操作；
  - **C** — 不强制。
- **建议**：A。
- **理由**：能读就等于完整的财务数据泄露；单用户每次登录多输一次 TOTP，成本很低。
- **选错的代价**：
  - A 下，TOTP 设备丢失时在恢复之前完全无法查看数据（可用性代价，按 P3-3 恢复）。
  - B 或 C 下，密码一旦泄露就能读到全部历史（机密性代价，不可逆）。

### P4-1 切换时的写入冻结方式

**决定（owner 已批准，2026-10-02）：A。** Production 切换时停掉 jobs、API、web，强制冻结写入。切换期间保持读服务可用**不是**切换的前提。


- **问题**：M8a 的 dump 期间，怎样保证没有任何写入。
- **可选方案**：
  - **A** — 停掉 jobs、api、web（强制冻结，应用在窗口期内不可用）；
  - **B** — 先在 M6 实现 API 只读模式，切换时保留读服务；
  - **C** — 不停服，只靠自觉不去改。
- **建议**：A。
- **理由**：
  - 现有代码没有只读模式。
  - 数据量小：dump 和恢复都是秒级，窗口主要花在校验上（推测几十分钟以内）。
  - 草案的 F1=F2 指纹比对能发现任何意外写入。
- **选错的代价**：
  - A 的代价只有窗口期内不可用。
  - C 一旦有写入漏进来，切换后这部分会丢失或分叉，需要回滚或手工补数据。
  - B 安全，但要求在 M6 多实现一个功能。

### P4-2 切换后的反向迁移能力

**决定（owner 已批准，2026-10-02）：A。** 在 Production 切换之前，于 M7 准备并演练一个本地 PG17 恢复环境。


- **问题**：Supabase 接受写入之后如果要回到本地，靠什么恢复。
- **可选方案**：
  - **A** — 在 M7 就准备并演练一个 PG17 的本地恢复环境，作为切换的前提；
  - **B** — 只做原地修复（fix-forward），不准备反向迁移；
  - **C** — 切换之后再准备。
- **建议**：A。
- **理由**：本地 Production 是 PG16，不能保证读取 PG17 的 dump；没有演练过的回滚路径等于没有回滚。
- **选错的代价**：
  - B 或 C 下，一旦云端出现严重故障或费用问题，只能等待修复。数据仍在独立备份里，但恢复环境未经验证，可能需要临时搭建，停机时间难以估计。
  - A 的代价是 M7 多准备一个镜像、做一次演练。

## 核实补充（00:23–00:25）

在任务全部完成后，又对文档中标为“未核实”的事项查了官方资料（2026-10-02），并已更新到各设计文档：
- pg_net 的 `pg_net.max_timeout_ms` 上游默认 600000 ms，300 s 在范围内；Supabase 项目上的实际值仍未核实。pg_net 不会自动重试。
- pg_cron 同一个 job 同时只跑一个实例，后来的一次会排队。
- Supabase JWT 默认有效期 1 小时，官方不建议低于 5 分钟。会话时长上限等功能只在 Pro 及以上提供。sign-out 会删除会话，但已签发的 access token 在 `exp` 之前仍然有效。
- 新项目从 2025-10-01 起默认使用非对称 JWT（官方博客）。
- 管理员可以用 `updateUserById` 直接设置密码，因此账号恢复可以不依赖邮件。
- GitHub-hosted runner 单个 job 最长 6 小时。
- 仍未核实的：runner 是否支持 IPv6；GitHub Free 私有仓库能否使用 releases（没找到官方原文）；Supabase Free 能否使用网络限制。
- 自查时更正了两处测试数量：backup 和 trigger 的数据库测试都是 3 个，不是 4 个。
- 读代码确认（`api/services/sync_all.py:421-424`）：没有到期 Item 时，`sync_all` 在加载历史之前就返回 `idle`。所以每 5 分钟一次的空 tick 很便宜，全量读取只在每天一次左右的到期同步时发生，按真实 payload 估算约 150 MB/月（Free 额度 5 GB）。

## 其他：需要批准或接手的操作

- **owner 记忆索引中有一行过期了**（`MEMORY.md` 里 "Sync diff-writes rollout … pending owner start time"，而对应记忆文件写的是“已部署”）。我尝试修正，被权限策略拒绝，没有再尝试，请你自己决定是否修改。已经成功写入的：新的 `m5-overnight-2026-10-02` 记忆；在 `production-approval-gates` 中补充“只有本次会话明确要求时，才在指定分支上 commit”的例外。
- 合并或 push `m5-remaining-20261002`：由你决定。我没有 push，没有合并，也没有改动 `main`。

## 已知问题（Production 配置时统一处理）

- **TEMP via PUBLIC（R16）**：合成项目上所有自建角色（`pft_m5_reader`、`pft_m5_jobs`、`pft_backup`）都能通过 PUBLIC 继承的 TEMP 权限创建临时表，已实测。owner 决定（2026-10-02）：现在不逐个修，放到 Production 配置时统一处理，已写入切换草案的前提条件 C4。做法是 `REVOKE TEMP ON DATABASE postgres FROM PUBLIC`，只给确实需要的角色显式授 TEMP。Supabase 内部角色是否依赖 TEMP 未核实，要在 M7 演练时确认。

## 未完成或受阻

今晚列出的五项任务没有受阻。以下是 M5 仍然开着、需要后续推进的事项（见 [盘点](PFT_M5_REMAINING_INVENTORY_2026-10-02.md)）：

1. **G7 备份**：P1-1 到 P1-5 已全部拍板；剩下的是需要批准的云端和账号操作（见第 6 项）。之后在合成项目上跑一次真实链路：PG17 dump 经 Supavisor（包括验证 `--snapshot` 能否穿过 session pooler）、上传、换机下载、恢复、指纹比对。
2. **R4 Cron**：在合成项目上启用 pg_cron、pg_net 和 Vault；核实 `pg_net.max_timeout_ms` 和 body 的实际字节；测重复投递、超时和过期场景。
3. **G6 Auth**：P3-1 到 P3-4 已拍板（2026-10-02）。下一步是 M6 的实现，以及在合成项目上跑反向测试矩阵，各自都需要单独批准。
4. **文档要求但今晚没做的**：R8（云端 catch-up、重试、部分失败的余量测试）、R9（应用 deadline 取值）、R10（取消后 `running` 状态的缺口，需要先给设计和策略）、R11（硬终止）、R13（分类的 O(n²) CPU）、R14（多实例连接预算）、R15（诚实的状态模型）、R19（$0 账单证据）、R21（M5 一次性资源的清理时间）。
5. 建议的下一步（P1-1 和 P1-2 定下之后）：在本地起草 workflow 和备份适配器（不需要任何云端操作）；再定 P1-4（加密格式），因为 workflow 里用哪个加密工具取决于它。需要你批准的云端操作见上方 P1 列表。

## 质量与验证说明

- 每次 commit 前都跑了相关测试、`git diff --check` 和通用 secret 模式扫描（私钥、JWT、带密码的 Postgres URL、Plaid、GitHub、AWS 等模式），结果全部干净。由于不允许读取凭据文件，**没有做“按真实凭据值”的比对扫描**。提交内容里只有今晚生成的文档、代码和合成测试，从未接触任何私有内容。
- 最终全套测试 326 个通过，0 跳过（7 个原有的 PG opt-in 加今晚新增的 2 个，并且故意设置了泄露的 `PLAID_PILOT_USER_ID`）。所有改动过的 Python 文件都编译通过，`git diff --check main` 干净。
- 前端没有改动，所以不涉及 build 和渲染 QA。没有任何服务需要重启。
- 一次性 PG16 集群（scratchpad，127.0.0.1:55439）已经停止并删除，临时脚本也已删除。
- 所有官方额度和限制都附了链接，查阅日期为 2026-10-02。查不到的标注为“未核实”；推测的内容标注为 [E] 或“推测”。

## 时间线与问题

- 23:55 开始；创建分支；读完全部 M5 文档与计划 §12–§16。
- 23:58 任务 1 开始：查官方文档，在 scratchpad 起一次性 PG16（127.0.0.1:55439）。
- 00:07 任务 1 测试与实测完成。
- 00:08 任务 2 开始；00:12 测试全部通过。
- 00:13 任务 3 开始（只写设计）；00:16 完成。
- 00:16 任务 4 开始（只写文档）；00:17 完成。
- 00:17 任务 5 开始；00:21 全套测试三种环境下均通过。
- 00:23 核实补充；00:25 提交。
- 00:26 最终全套测试；删除一次性集群；00:27 收尾。
- 遇到的问题：恢复时 `public` schema 冲突，以及 CHECK 约束被等价改写（都已在任务 1 中处理）；`tests/` 没有 `__init__.py`，`unittest discover` 不可用，改为显式列出模块运行；修正记忆索引被权限策略拒绝（见上）。
