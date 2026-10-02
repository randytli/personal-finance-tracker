# M5 无人值守夜间工作交接 — 2026-10-02

分支：`m5-remaining-20261002`（从 `main` @ `47183eb` 创建；未 push，未合并，未改动 `main`）。

开始时间：2026-10-01 23:55 EDT（`date` 实测）。结束时间：见文末。

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

- 产出：[设计文档](PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md)、`scripts/pft_m5_backup_drill.py`（原型）、`scripts/pft_m5_backup_fixture.py`（合成数据，15 张表全部有数据）、`tests/test_m5_backup_drill.py`（12 个测试）、[实测结果](evidence/m5-2026-10-02/backup-drill.json)。
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

## 待决（需要 owner 拍板或批准）

### 任务 1：备份

- **P1-1 存储选择**。建议：主存储用一个专用的 GitHub 私有仓库，每份备份是一个 release asset。理由：
  - 不需要绑卡；
  - Actions 在没有付款方式时超额会被直接阻止（官方原文）；
  - releases 官方写明“总大小与带宽不限”；
  - 独立于 Supabase 和 Vercel。

  风险：GitHub AUP 保留对“过度占用”的处置权；同一个 token 既能上传也能删除。B2 仍是备选，但它的闸门由你关闭，我没有动它。R2 和 GCS 要求结账流程或 billing account，又没有硬上限，所以不建议。
- **P1-2 备份在哪里跑**。建议：用 GitHub Actions 定时 workflow，使用固定 digest 的 `postgres:17.11` 镜像，只连只读备份角色。好处是和 `tick` 及 Vercel 的 300 s 完全解耦，消除 R3（备份先于同步、取消后线程仍在跑）。代价是多出一个“只读的第二个调度器”，与计划“一个调度器”的措辞有冲突，需要你接受。如果不接受，就改为由 Supabase Cron 分派一个独立的 Vercel 备份 job kind。
- **P1-3 第二份副本**。建议：你每周或每月手动下载最新一份，放到 Google Drive 或离线介质，用来防 GitHub 账号丢失。不给自动化任何 Drive 凭据。
- **P1-4 加密格式**。PFTENC3 由经过审查的原语组合而成，但格式是自定义的。建议在 M6 实现前请人独立审查一次；也可以改用标准的 `age`，代价是每个恢复环境都要多一个二进制。
- **P1-5 备份频率**。建议：每日一次，外加每次迁移、切换或 schema 变更前手动补一次。每日两次可以把 RPO 减半，成本可以忽略。
- **需要批准才能执行的操作**：
  - 创建备份仓库和 workflow；
  - 你离线生成真实密钥对，只把公钥交给 workflow；
  - 在 M5 合成项目上创建只读备份角色；
  - 在合成项目上跑一次真实的“PG17 dump → 上传 → 换机下载 → 恢复 → 指纹比对”；
  - 核实 `PROVIDER_SCHEMAS` 列表（目前未核实，原型遇到未知 schema 会直接失败）。

### 任务 2：Cron

- **P2-1 节拍**。建议：先用 5 分钟（每月 8,640 次，计划给的起点）。1 分钟（每月 43,200 次）能恢复今天 ≤60 s 的手动延迟，但 CPU 和连接成本未测，等云端实测后再决定。
- **P2-2 接受“可能被暂停”**。官方给出的防止办法是付费升级，计划又禁止保活流量。建议接受：真实的同步流量本身大概率能维持活跃（推测）。一旦暂停，靠官方的警告邮件和 PFT 的过期告警发现，然后手动恢复。
- **P2-3 pg_net 怎样穿过 Vercel 部署保护**。可选：(a) 部署到不受保护的 production 目标，只靠 HMAC 保护；(b) 使用 automation bypass 头，多一个存在 Vault 里的秘密。建议 (a) 加 HMAC，因为 bypass 头只是静态秘密，比 HMAC 弱。这需要你确认 production 目标不暴露任何其他路由。
- **需要批准的操作**：在 M5 合成项目上启用 pg_cron、pg_net 和 Vault，部署带校验的 jobs preview，跑一次真实的节拍、重复投递和超时测试（见设计 §5）。

### 任务 3：Auth

- **P3-1 会话模型**。建议：Supabase SDK cookie 加 Next.js 服务器代理，而不是完整的 BFF。理由：
  - 完整 BFF 只能防 XSS 偷 token，防不了 XSS 冒用当前会话；
  - 它还要额外实现会话表、加密密钥、CSRF、刷新串行化，对单用户来说是更多的安全关键代码；
  - 计划允许在明确接受这一取舍后使用这个模型。

  配套措施：严格 CSP、MFA、短 JWT 有效期。
- **P3-2 Python JWT 库**。建议 PyJWT（它会用到已经固定版本的 `cryptography`），版本在 M6 固定。这会新增一个依赖。
- **P3-3 账号恢复**。建议走完全不经邮件的路径：先登录 Supabase 控制台（控制台账号必须开 MFA），再在可信机器上用 secret/service_role key 调用 `auth.admin.updateUserById` 重设密码。官方文档有这个设置 password 的示例，并要求只在服务器端调用（已核实，2026-10-02）。默认 SMTP 只能发给团队成员，每小时 2 封，而且是尽力投递，不宜作为主路径。通过 admin API 删除丢失的 TOTP 因子，未核实。
- **P3-4 aal2 范围**。建议所有金融路由都要求 aal2。
- **需要批准的操作（仅限合成项目）**：建 owner 用户并关闭注册、启用 TOTP、迁移到非对称签名密钥、关闭 Data API、建上述角色，然后跑反向测试矩阵。

### 任务 4：切换

- **P4-1 冻结方式**。现有代码没有只读模式，所以草案选择停掉 api/web，换取强制的写入冻结，代价是窗口期内应用不可用。另一种做法是先在 M6 实现只读模式，再保持读服务在线。建议 M8a 沿用“停服冻结”，简单可靠。
- **P4-2 反向迁移的能力**。切换之后，本地的 PG16 不能保证恢复 PG17 的 dump。建议在 M7 就准备并演练一个 PG17 的本地恢复镜像，作为回滚的前提（C5）。

## 核实补充（00:23–00:30）

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

## 未完成或受阻

（随各项更新）

## 时间线与问题

- 23:55 开始；创建分支；读完全部 M5 文档与计划 §12–§16。
- 23:58 任务 1 开始：查官方文档，在 scratchpad 起一次性 PG16（127.0.0.1:55439）。
- 00:07 任务 1 测试与实测完成。
- 00:08 任务 2 开始；00:12 测试全部通过。
- 00:13 任务 3 开始（只写设计）；00:16 完成。
- 00:16 任务 4 开始（只写文档）；00:17 完成。
- 00:17 任务 5 开始；00:21 全套测试三种环境下均通过。
