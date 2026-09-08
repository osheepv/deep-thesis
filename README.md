# Deep Thesis

M13 已补充真实 HTTP API 与独立 Worker 的故障恢复演练：模型请求期间强杀、自然租约到期接管、TCP 断连失败后人工重试、API 重启后保留产物和待审批状态。采用本机模型故障服务，不调用真实供应商，公网发布环境验收仍待执行。详见[M13验收报告](docs/M13部署入口故障恢复验收_2026-09-08.md)。

存储迁移现支持把**登记完整、当前表结构**的分散数据库和附件复制到新的统一目录，预检默认不发布目标，并修正任务、文献、模板和下载路径。使用 `python -m application.migrate_storage --plan ... --stopped`，通过后加 `--apply`；迁移后必须启动对账。见[存储迁移指南](docs/存储迁移指南.md)。源数据保留，历史内存登记缺失会明确阻断。

M12 已增加统一数据目录的停机备份、SHA-256 / SQLite 完整性校验和原路径恢复。使用 `python -m application.backup create|verify|restore`（安装命令 `deep-thesis-backup`）；具体参数、停机要求和回退步骤见[数据备份与恢复指南](docs/数据备份与恢复指南.md)。该阶段相关回归 21 项通过，恢复后的真实任务对账及成稿下载通过；发布环境故障演练仍待完成。见 [M12 验收报告](docs/M12停机备份与恢复验收_2026-09-08.md)。

[![CI](https://github.com/osheepv/deep-thesis/actions/workflows/main.yml/badge.svg)](https://github.com/osheepv/deep-thesis/actions/workflows/main.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Discussions](https://img.shields.io/badge/GitHub-Discussions-6f42c1)](https://github.com/osheepv/deep-thesis/discussions)

学位论文全流程智能写作工作台的工程化原型：FastAPI 后端、十阶段状态机、文献与知识库基础、docx 管线和桌面式 Web UI。

> 名称与依赖说明：产品统一命名为 **Deep Thesis**。项目不依赖 DeepSeek-Harness；当前通过 OpenAI 兼容接口直接接入 DeepSeek，后续模型提供商能力将继续通过适配层演进。

> 准确定位：项目已经具备可信的十阶段控制流，但还不是可稳定交付完整本/硕/博论文的成品。当前重点是把整批生成改造成可编辑、可版本化、逐条绑定证据的分节写作系统。产品边界和建设路线见 [产品架构蓝图](docs/产品架构蓝图.md)，界面规范见 [DESIGN.md](DESIGN.md)。

> 2026-09-06 真实供应商复验：本科、硕士、博士代表任务均已使用真实模型完成10/10环。博士任务真实触发长章节不足和润色过度压缩，修复后通过章节中间检查点、进程重启和旧检查点自愈完成续跑，最终初稿61,411字、润色稿61,461字。该结果证明控制流与恢复链可运行，不代表正文论断已获得全文证据，也不代表成稿可无人审查提交。详见 [本科验收报告](docs/真实模型本科十环验收报告_2026-08-26.md)、[M6硕士验收报告](docs/M6硕士真实全流程与章节余量验收_2026-09-05.md) 和 [M7博士验收报告](docs/M7博士真实全流程与长稿恢复验收_2026-09-06.md)。

## 项目定位

依据《学位论文全流程标准化规范（本硕博）》（[docs/学位论文全流程标准化规范_本硕博.md](docs/学位论文全流程标准化规范_本硕博.md)）的 10 环节状态机，把论文写作从经验流程抽象为可执行、可校验、可回退、可人工确认的工作流。本硕博共用同一骨架，通过验收阈值、引用深度、大纲层级与最低字数要求体现差异。

### 核心特性：跨天写作与断点续作

论文是持续数周或数月的项目，不是一次聊天。任务、当前环节、产物版本、作者决定、待审批闸门、章节检查点和后台作业必须以持久化数据为真相源，不依赖模型上下文或浏览器页面存活。用户任意时刻退出、断网或重启后，应能看到“上次停在哪里、已完成什么、下一步是什么”，且已计费完成的工作不得无故重跑。

### 核心体验：内置优先与外部软件连接

文献、笔记、双链、图谱、证据、引用和写作的核心操作必须在论文工作台内完成，不把Obsidian、Zotero等软件变成必装依赖。已有外部资料的用户可以通过Zotero官方API、Obsidian授权Vault、通用文件或受限REST/MCP连接器接入；连接器离线不阻断写作，外部变化也不能绕过版本、证据等级和人工审批。详见[内置能力与本地软件连接器架构](docs/内置能力与本地软件连接器架构_2026-08-30.md)。

## 当前状态

当前已落地：

- 十环执行体已接入主编排；每一环都严格执行“生成产物 → 自动验收 → `WAITING_APPROVAL` → 用户确认 → 下一环”。
- 跨环执行、无产物推进和重复执行待确认环都会被拒绝；环10最终确认后进度为 100%。
- 正式模式默认关闭静默 Mock。模型未配置或调用失败时明确报错；测试/演示需要显式开启 Mock。
- 环3支持 Crossref、OpenAlex、Semantic Scholar 等来源及中文检索引导；空文献池不再被当成成功。
- 环8无可核验引用时失败，环10材料缺失时失败；外部元数据命中不等同于全文事实已核验。
- 环8现分别展示“结构、题录/元数据、正文证据、作者复核”；旧`[L序号]`路径即使DOI全部命中，也不会冒充为正文证据通过。
- 知识库与会话 1:1 绑定，包含文献文件、笔记、双链、图谱和本地 RAG 基础。
- 任务、各环产物和 FSM 状态使用 SQLite 持久化；docx 生成、下载与版式检查已串联。
- 任务列表、当前环、待审批闸门、项目记忆、分节版本、章节检查点和Job状态已可在刷新/进程重启后恢复，不以当前聊天记忆作为唯一依据。
- `/api/v1/tasks`与`/api/v1/console/tasks`共用同一编排、FSM和持久化任务记录；`db.models`只重导出唯一运行时ORM，不再维护冲突表定义。
- RAG支持PDF、DOCX、TXT和Markdown提取，采用向量余弦+轻量BM25混合检索；嵌入模型不可用时仍可关键词检索。
- 阶段审批通过事务 Outbox 投影为不可变版本产物；上游改版会递归将下游标记为过期。
- 已实现来源、可定位摘录、论断和证据链接账本；未经作者复核的摘录不能支撑正文论断。
- 已实现研究协议、实验运行状态机、原始材料血缘和结果账本；实证类任务未批准结果账本时禁止生成初稿。
- 已实现论证图的有向无环校验与审批；核心论断自动登记到证据账本，大纲对论证版本建立依赖。
- 环6支持按节最小上下文生成、独立版本、自动验收、逐节审批和完整性汇编；上游失效会使相关分节过期。
- 环1候选题由作者显式选择并持久化为后端事实；多候选未选择时禁止确认。
- 环3支持候选文献纳入/排除/排序，按选题词法相关度重排并显示命中词；确认条目以RIS题录登记到任务知识库。
- 环3只会把知识库中明确标记为`literature`的文件并入文献候选；原始数据、代码、日志和图片不会混入，用户上传也不再自动标为已核验文献。
- 环6/7执行学位级硬质量门禁：本科/硕士/博士最低字数分别为1万/3万/6万，并校验章节、引用、结果、书签、占位文本和生成来源；Mock/降级稿不能伪装为通过。
- 环6/7采用逐章调用并保存章节级检查点；环6按剩余全文字数动态分配章节目标，每次补写都持久化未完成章节，重试只携带标题和正文末尾继续补写，避免丢失已计费内容或重复整章输入。
- DeepSeek V4结构化JSON调用默认显式关闭高思考模式，避免推理Token耗尽后最终`content`为空；可通过环境变量重新启用。
- 当前仅支持DeepSeek接口；前端可运行时设置DeepSeek API Key、Base URL、模型、思考模式和能力标记。密钥不回显、不写入浏览器或数据库，进程重启后恢复`.env`。
- 环3检索策略与环6写作计划已接入可选的有界Agent Loop：只能调用宿主注册的只读工具，强制轮数、工具数、观测长度和输出Token上限，默认关闭以避免未预期费用。环3当前可读已批准选题/项目记忆并检查相关度与查询语法；环6可搜索已登记资料、核验引文和章节覆盖。
- 环6 Agent Loop已完成真实DeepSeek V4 Flash小规模验收：2章计划在6轮、11次只读工具调用内收敛，消耗8570 Token，所有建议引文均通过`check_citation`实际核验。详见[真实DeepSeek Agent Loop验收报告](docs/真实DeepSeek_Agent_Loop验收报告_2026-08-27.md)。
- M6 已完成硕士真实十环验收：真实任务经过两次断点续跑后 10/10 环通过；健康状态 `UP`、启动对账 `CONSISTENT`、任务进度 `100%`。脚本默认安全预检，只有显式 `--execute` 才产生真实调用。详见[M6硕士真实全流程与章节余量验收](docs/M6硕士真实全流程与章节余量验收_2026-09-05.md)。
- M7 已完成博士真实十环验收：七章初稿与润色稿均超过6万字；环6未完成章节可跨Job/进程续写，环7过度压缩会保留原章并自愈旧检查点。详见[M7博士真实全流程与长稿恢复验收](docs/M7博士真实全流程与长稿恢复验收_2026-09-06.md)。
- 环7增加逐章长度保真门禁：候选稿至少保留原章90%，并根据剩余原文保证全文不低于学位字数要求；过短候选不会覆盖已通过的初稿。
- 论文级项目记忆已落地：研究问题、范围硬边界、禁写主张、待补证据/未决主张、作者决定、导师意见、术语、写作风格和自动修订停止预算以不可变版本登记，自动校验后必须作者审批；缺关键证据与未解决专家冲突始终优先停止，轮数/增分平台期只限制自动修订而不限制作者手工修改。自由文本不得自报“已证实”，研究事实仍须由批准 Evidence 或用户核验 Result 投影。详见[NAT-001任务卡](docs/NAT-001学术基础契约接入任务卡_2026-09-02.md)。
- M2 已增加只读 Research Canon / Evidence Table 投影：`/api/v1/console/tasks/{task_id}/academic-foundation` 只返回批准产物与来源的 ID/版本/hash、范围边界、结果标识和主张级审计字段，不复制摘录、结果值或完整 payload；`epistemic_intent`、`evidence_state`、`verification_strength`、`risk_level` 由服务端重算，证据缺口会让 `can_write=false` 并显示阻断主张。详见[NAT-001任务卡](docs/NAT-001学术基础契约接入任务卡_2026-09-02.md)。
- M3 已把确定性 `SectionContract` 嵌入批准大纲的每个叶子节点：合同固定写作目的、输入产物、允许论断、禁写主张、证据/结果要求与校验清单；分节生成前缺材料不会调用模型，生成后的合同外论断、证据、结果或禁写主张会自动拒绝。`ContextManifest` 和 `gate_report` 同时记录 `canon_hash/contract_hash`，环5界面可展开评审合同摘要。
- M4 已把批准项目记忆接入大纲的正式依赖图：新记忆版本会递归使大纲和相关分节过期；环7润色前复跑合同、证据、结果和输入产物审计，阻断时进入 RECOVER_STAGE 且不调用模型；Resume 仅提供原因码、阻断数量和安全下一步，不返回正文或证据原文。
- M5 已增加跨任务存储启动对账：自动重放产物 Outbox、回收过期 Worker 租约，并检查任务/FSM、批准产物、分节版本、Job 与知识库血缘；其他冲突进入 `REPAIR_REQUIRED` 并禁止环确认。健康检查和只读对账接口只暴露状态与原因码。详见 [M5 验收报告](docs/M5启动对账与故障矩阵_2026-09-05.md)。
- M8 已验证本机 Worker 强杀后的真实租约到期恢复、3进程竞争领取24个作业、本地连接中断和作业人工重试；修复心跳/取消/重试竞态，过期 Worker 不能续租、登记完成或开始新模型调用。正式部署网络故障验收仍待完成。详见 [M8验收报告](docs/M8后台作业进程故障与并发验收_2026-09-06.md)。
- M9 已为业务写入接入执行凭证和租约栅栏；M10 已验证独立子进程强杀、停止心跳后自然到期、同名 Worker 接管、迟到写入拒绝和重开数据库后的章节/产物保留，并修复等待数据库锁时租约时间过早计算的问题。详见 [M9验收报告](docs/M9业务写入执行凭证与租约栅栏验收_2026-09-06.md)和 [M10验收报告](docs/M10进程级章节恢复与锁等待验收_2026-09-07.md)。
- 环7/8失败后可安全回到可修订环节，恢复入口同时识别FSM失败态与当前环FAILED Job。
- 新分节链路的环8会审计正文证据/结果标记，生成稳定引文编号、GB/T 7714参考文献和结果交叉引用清单。
- DOCX 生成器会把Markdown正文转换为可编辑的Word标题/正文/参考文献段落，把明确的 `BOOKMARK/REF` 标记转换为原生书签与 `REF` 域；环9会拒绝仍折叠为单个模板文本块的假排版。
- 长耗时环执行、分节生成和 DOCX 生成可进入持久化 JobRun；支持幂等入队、Worker 租约/心跳、崩溃恢复、协作取消、失败重试及 Token/费用预算。
- 前端支持十环进度、人工确认闸门、后台作业与预算、证据/论证审计、分节生成/修订/审批，以及刷新后的状态恢复。
- 前端“记忆”工作台可创建、审批、驳回和基于旧版修订项目记忆；表单错误与状态更新已通过真实浏览器验收。
- 前端已外置CSS和主运行时，项目记忆与证据概览使用独立功能模块和冻结的小接口；证据面板并发刷新会拒绝过期响应，局部加载失败不再伪装成空数据。
- 前端视觉层已接入本地 Lucide 图标与 Open Props 阴影/动效 Token，十环进度、空状态和主要工作台保持离线可用；运动敏感用户会自动关闭非必要动画，受限完成态与正常完成态使用不同图标而非只靠颜色区分。依赖来源与许可证见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 前端交互已完成一轮真实浏览器加固：默认本地 CORS 可直接连接 API，任务列表刷新会保留当前任务，搜索支持中英文/学位/阶段过滤、无结果提示、Esc 清除和结果数播报。
- 前端支持作者候选题选择、文献筛选排序、失败恢复、实时阶段摘要、批量分节操作和自适应Job轮询；Cytoscape已改为本地静态依赖，离线启动不再访问公共CDN。
- 研究工作台可视化创建并审批研究协议/论证图，上传实验材料、原始数据、代码和日志，推进实验状态、登记/核验结果及批准结果账本。
- 分节工作台可选择任意两个版本进行双栏行级差异比较；学校 DOCX 模板会持久化并支持中英文占位符映射，未映射字段会阻断生成。
- 可选生产认证层提供 HttpOnly 不透明会话、scrypt 密码哈希、登录锁定、owner/editor/reviewer/viewer 授权、任务/知识库租户隔离和不可变操作审计。
- `demo_run.py` 提供最小严格流程冒烟；`demo_full_10.py`/`scripts/real_full_flow_acceptance.py`按真实Job预算、作者选题、文献筛选和逐环确认协议运行，并生成不含正文与密钥的验收报告。
- 后端可构建标准wheel，提示词和内置DOCX模板随包分发；核心运行依赖与可选PostgreSQL/Redis基础设施依赖已分离。
- 用户工作区位置（最后论文任务、工作台页签、稳定展开项和分节编辑锚点）已持久化到 SQLite 并按租户 + 用户隔离；刷新与后端进程重启后能继续上次论文。作者私有自动草稿已覆盖分节修订、项目记忆、研究协议和论证图四个真实编辑面：按任务/租户/作者/`draft_key`隔离，以服务端 SQLite 和单调 `revision`为真相源，支持防抖保存、pagehide末次保存、刷新/进程重启恢复、过期标记与多页面显式冲突处理。正式提交成功后转为 `SUBMITTED`，失败仍保留 `ACTIVE`；草稿不推进 FSM、不创建正式产物、不进入 Agent 上下文、不触发模型调用。恢复摘要只返回 `ACTIVE/STALE` 草稿元数据，不返回正文，并在适用时给出 `RESUME_DRAFT`。详见[断点续作第一阶段验收报告](docs/断点续作第一阶段_2026-08-29.md)和[H4-002阶段报告](docs/H4-002自动草稿阶段报告_2026-08-30.md)。
- 工作区位置采用服务端可验证的单调 `revision`：客户端在发送时同步预留递增版本，服务端在锁内做比较并写入，乱序到达的旧 POST 一律被拒绝；删除任务与自愈幽灵指针等服务端修改会生成更高 revision；同 revision 不同内容返回明确冲突而非静默覆盖；冲突只影响 UI 位置，不改变 FSM、Artifact 或正式论文状态。保存控制器按身份世代隔离，旧身份的在途请求不会阻塞新身份的首次保存。Job、FSM 或审批状态变化后，可见的“继续上次论文”横幅会强制重取最新摘要，拿不到准确摘要时立即隐藏。详见[断点续作第一阶段验收报告](docs/断点续作第一阶段_2026-08-29.md)的 H4-001R 修复记录。

当前关键缺口：

- 结构化表格/图片编辑器、复杂公式管线和学校模板样式差异诊断仍待完成。
- UI已完成第一步无构建拆分，但主`app.js`仍偏大；桌面打包、独立 Worker 运维、MFA/SSO 和密钥托管尚未完成。
- 需要把环6的有界Agent和已批准项目记忆扩展到更多环节，并补齐流式进度和变更级HITL。
- 需要继续补充全文相关性/证据评测、提示词回归，以及发布环境的运行中强杀、真实断网、Worker租约、并发和人工回退压力演练。
- 断点续作已交付最后任务、活动页签、继续入口、自动草稿、稳定展开项、分节编辑锚点、全域启动对账与自动化故障矩阵；下一步是发布环境的真实进程强杀/断网演练，以及后续多人协同能力。

## 欢迎参与讨论

这个项目现已公开，希望听到真实用户、研究者和开发者对“智能体如何协助论文写作全流程”的不同看法。

- 发现缺陷、交互问题或学术安全风险，请提交 [Issue](https://github.com/osheepv/deep-thesis/issues)。
- 产品方向、工作流设计、Agent协作、知识库与引用规范等开放问题，欢迎在 [Discussions](https://github.com/osheepv/deep-thesis/discussions) 中交流。
- 提交建议时，请尽量说明使用场景、期望行为和当前问题；请勿上传未公开论文、个人信息、API密钥或受版权保护的全文材料。

所有反馈都会作为产品迭代参考，但本项目不会代替作者、导师或学校完成学术真实性、研究伦理和最终质量审查。

参与前请阅读 [贡献指南](CONTRIBUTING.md)、[社区行为准则](CODE_OF_CONDUCT.md)、[安全政策](SECURITY.md) 和 [产品路线图](ROADMAP.md)。

需要跨模型或跨会话续接开发时，请先阅读 [混元4项目执行总指挥手册](docs/混元4项目执行总指挥手册_2026-08-29.md)。该手册记录当前安全基线、未完成代码现场、阶段任务边界、测试门禁和GitHub同步规则。

## 模块映射（对齐系统设计 M1~M9 落地状态）

| 模块编号 | 模块名称 | 目录 | 状态 |
| --- | --- | --- | --- |
| M1 | FSM 编排器 | `backend/fsm/orchestrator/` | ✅ 已实现（10 环状态机 + HITL 闸门 + 回退） |
| M2 | 环节执行体 | `backend/executor/`、`backend/writing/` | 🟡 十环、证据约束分节写作、修订审批和汇编已接入；版本差异待建设 |
| M3 | 验收 Gate / HITL | `backend/fsm/` | ✅ 执行/验收/确认分离，所有环人工确认 |
| M4 | 状态存储 | `backend/db/`、`backend/fsm/repository/`、`backend/application/service/task_store.py`、`backend/writing/draft_store.py` | ✅ SQLite（任务/FSM/工作区/自动草稿及各域账本） |
| M5/M6 | docx 解析/生成 | `backend/thesis_docx/` | ✅ 用户模板持久化/映射、docxtpl、版式检查、原生书签/REF 域及严格 OOXML 验证 |
| M7 | 查重 | — | 预留（OOS：只提醒人工自建查重） |
| M8 | Guardrail | `backend/common/`、`backend/evidence/`、`backend/research/` | ✅ 来源/摘录/论断、结果血缘、环8强制审计和 DOCX 域验证 |
| M9 | 知识库 | `backend/knowledge/` | ✅ 已实现（文件池/笔记双链/图谱 API + RAG 检索） |
| 执行治理 | JobRun/预算 | `backend/jobs/` | ✅ 持久化队列、租约恢复、取消重试、Token/费用登记 |
| 安全治理 | 认证/授权/审计 | `backend/security/` | ✅ 可选 fail-closed 认证、租户隔离、角色授权、会话撤销和操作审计 |
| 环内智能体 | 有界只读Agent Loop | `backend/common/agent_loop.py`、`backend/executor/ring3/`、`backend/executor/ring6_chapter.py` | 🟡 环3检索策略与环6写作计划试点已实现；默认关闭 |
| 项目记忆 | 版本化长期上下文与停止预算 | `backend/common/project_memory.py`、`backend/artifacts/` | ✅ 研究问题/边界/禁写与未决主张、停止原因码、版本审批、环6强制只读消费和前端管理已实现 |
| 公共 | 公共模块 | `backend/common/` | ✅ 已实现（DeepSeek客户端 / 文献服务 / 引用格式化 / 提示词仓库） |

## 环境准备

```bash
python -m venv .venv
# PowerShell
.\.venv\Scripts\Activate.ps1
# 开发与测试
python -m pip install -r backend/requirements.txt
# 或安装运行包
python -m pip install ./backend
# 需要PostgreSQL/Redis/Alembic时再安装可选依赖
python -m pip install -r backend/requirements-production.txt
```

默认使用 SQLite，不需要 PostgreSQL。真实模型与文献服务由环境变量启用。

## 运行服务

```bash
cd backend
# 必须先配置 .env（复制 .env.example 并填 DeepSeek key）
python -m uvicorn application.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs 查看 Swagger。

需要把后台作业与 API 分开运行时，两端设置相同的绝对 `THESIS_DATA_DIR`，API 设置 `THESIS_JOB_WORKER_ENABLED=false`，另开终端运行 `python -m application.worker --check`，对账通过后运行 `python -m application.worker`。安装包也提供 `deep-thesis-worker` 命令；新模式持久化模板及下载记录。完整步骤与旧数据处理见[独立 Worker 部署指南](docs/独立Worker部署指南.md)，验证范围见[M11验收报告](docs/M11独立Worker与共享存储验收_2026-09-08.md)。

**前端 UI**（Claude 桌面风格界面，独立端口）：

```bash
# 用任意静态服务器托管完整 ui 目录（必须保留 js/styles/vendor 相对结构）
cd ui
python -m http.server 8787
```

浏览器打开 http://localhost:8787（后端 8000 需同时运行）。

前端仍使用原生HTML/CSS/JavaScript且无npm构建步骤；`pip install ./backend`只安装API后端，不包含UI静态资源。前端目录与加载顺序见[UI说明](ui/README.md)。

后端默认只允许 `http://127.0.0.1:8787` 与 `http://localhost:8787` 的带凭证跨域请求。部署到其他域名时，通过 `THESIS_CORS_ORIGINS` 逗号分隔显式配置真实前端来源；认证模式禁止使用 `*`。

## 运行测试

当前回归基线：**415 项 pytest 全部通过**（2026-09-08），另有 **31/31 条离线学术质量规则 case 通过**。M5 新增启动对账与故障矩阵，M6 增加硕士真实全流程预检和章节余量回归，M7 增加未完成章节持久化、博士长稿恢复与润色压缩守护，M8 增加进程故障、租约与并发竞态测试，M9 增加业务写入执行凭证与租约栅栏，M10 增加进程级章节恢复和锁等待计时回归，M11 增加独立 Worker、共享存储和跨进程文件下载验证。

基线演进按公共 Git 历史说明：H4-001R 为 278 项；H4-002 自动草稿完成并修复幽灵草稿/提交墓碑竞态后为 315 项；H4-003 评测契约进入 pytest 后为 327 项；环3 Agent Loop 首版为 337 项；正式编排接线、检索词扩展恢复与 fail-closed 契约补齐后为 352 项；本地视觉依赖契约进入后为 353 项；NAT-001 M1 学术边界与停止规则契约进入后为 364 项。数字以实际运行 `python -m pytest tests -q` 的结果为准。

```bash
# 项目根执行（conftest 自动注入路径）
python -m pytest tests -v
# 离线学术质量规则评测（不冒充真实模型质量结论）
python evals/run_academic_eval.py --suite all
```

真实DeepSeek Agent小规模验收默认只做安全预检；显式加`--execute`才会产生有上限的真实调用：

```bash
python scripts/real_agent_loop_acceptance.py
python scripts/real_agent_loop_acceptance.py --execute
```

## 数据库结构

当前运行时唯一ORM定义位于`backend/fsm/state/orm.py`，默认使用SQLite并由SQLAlchemy在开发期建表。`backend/db/ddl.sql`是早期PostgreSQL目标设计，仅作参考；在完成正式Alembic基线和迁移演练前，**不要直接用于生产数据库**。

下一阶段会把FSM、任务业务记录、产物账本和知识库的PostgreSQL迁移收敛为可版本化Alembic schema。

## 技术栈（运行依赖见 backend/requirements-runtime.txt）

Python 3.13 · FastAPI 0.115.12 · SQLAlchemy 2.0.41 · SQLite（过渡；后期可迁 PostgreSQL）·
DeepSeek OpenAI格式客户端（当前唯一支持的模型供应商）· docxtpl 0.20.2 · openxml-audit 0.7.5 ·
sentence-transformers 3.4.1（BAAI/bge-small-zh-v1.5 本地嵌入，RAG 零成本）· pypdf ·
Cytoscape.js 3.30.2（知识图谱）· pytest 8.3.5

## 环境变量

后端读取 `backend/.env`（模板见 `backend/.env.example`，**.env 严禁提交 git**）：
`THESIS_DEEPSEEK_API_KEY` / `THESIS_DEEPSEEK_BASE_URL` / `THESIS_DEEPSEEK_MODEL` / `THESIS_DEEPSEEK_FALLBACK_TO_MOCK` / `THESIS_DEEPSEEK_THINKING_MODE` / `THESIS_DEEPSEEK_REASONING_EFFORT` /
`THESIS_DEEPSEEK_SUPPORTS_TOOLS` / `THESIS_DEEPSEEK_SUPPORTS_VISION` / `THESIS_AGENT_LOOP_ENABLED` / `THESIS_AGENT_LOOP_MAX_TURNS` /
`THESIS_DB_URL` / `THESIS_LIT_ENABLED` / `THESIS_LIT_SCOPE` /
`THESIS_METASO_ENABLED`（默认 false，省钱）/ `THESIS_RAG_ENABLED` / `THESIS_CORS_ORIGINS` /
`THESIS_DATA_DIR` / `THESIS_DOCX_DB`（统一目录模式）/ `THESIS_TASK_STORE_MEMORY`（测试用）/ `THESIS_ARTIFACT_DB` / `THESIS_EVIDENCE_DB` /
`THESIS_RESEARCH_DB` / `THESIS_SECTION_DB` / `THESIS_AUTOSAVE_DB` / `THESIS_JOB_DB` /
`THESIS_JOB_WORKER_ENABLED` / `THESIS_LLM_INPUT_COST_PER_MILLION` /
`THESIS_LLM_OUTPUT_COST_PER_MILLION` / `THESIS_KB_MAX_FILE_MB` /
`THESIS_AUTH_ENABLED` / `THESIS_AUTH_BOOTSTRAP_TOKEN` / `THESIS_SECURITY_DB`。

## API 示例

见 `docs/api_examples.md`。

## 许可证

项目自有代码采用 [Apache License 2.0](LICENSE)。第三方组件继续适用各自许可证，详见 [第三方软件声明](THIRD_PARTY_NOTICES.md)。
