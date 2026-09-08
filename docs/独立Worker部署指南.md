# 独立 Worker 部署指南

M11（2026-09-08）提供单机 API / Worker 分离运行入口。API 接收操作和作业请求，独立 Worker 从同一持久化队列领取作业。默认 API 内置 Worker 的开发模式仍可使用。

## 安装与共享配置

先在项目根目录安装后端与所需依赖：

```shell
python -m pip install ./backend
```

以下 PowerShell 配置须在 API 和 Worker 两个终端分别设置，使用完全相同的绝对数据路径：

```powershell
$env:THESIS_DATA_DIR = 'C:\DeepThesisData'
$env:THESIS_TASK_STORE_MEMORY = 'false'
$env:THESIS_JOB_WORKER_ENABLED = 'false'
```

模型参数、DeepSeek 密钥和启用状态也需要在两个进程中保持一致。通过各自进程环境或同一个受保护的部署配置注入；不同启动目录中的 `.env` 不应被当作共享配置。独立 Worker 不需要接收认证请求，API 的认证配置仍按 README 设置。

`THESIS_DATA_DIR` 模式默认将以下数据收敛到该目录：

| 内容 | 默认相对位置 |
| --- | --- |
| FSM | `thesis.db` |
| 任务记录 | `task_store.db` |
| 作业、产物、证据、研究、分节、自动草稿 | `jobs.db`、`artifacts.db`、`evidence.db`、`research.db`、`sections.db`、`autosave.db` |
| 模板及生成文件登记 | `docx.db` |
| 认证数据 | `security.db` |
| 知识库、模板文件、生成文件 | `kb/`、`templates/`、`outputs/` |

已有 `THESIS_DB_URL`、`THESIS_TASK_STORE_DIR`、各 `THESIS_*_DB`、`THESIS_KB_ROOT`、`DOCX_UPLOAD_DIR`、`DOCX_OUTPUT_DIR` 显式环境配置优先，必须在两端一致。此模式拒绝相对路径和内存存储；SQLite FSM URL 必须指向绝对文件路径。数据库不可用时拒绝启动，不回退内存 FSM。

## 启动

先在 Worker 终端检查存储与启动对账：

```powershell
python -m application.worker --check
```

输出 `reconciliation=CONSISTENT` 后，在 API 终端启动：

```powershell
python -m uvicorn application.main:app --host 127.0.0.1 --port 8000
```

然后在 Worker 终端执行：

```powershell
python -m application.worker
```

安装包也提供等价命令 `deep-thesis-worker`。直接从源码运行时，进入 `backend` 目录再执行模块命令；安装包方式不依赖当前目录。首次初始化时按顺序启动，先使用一个 API 进程和一个 Worker 进程。

`THESIS_JOB_WORKER_ENABLED=false` 仅关闭 API 内置 Worker，不会禁用独立入口。只有进入 JobRun 队列的操作由独立 Worker 处理，已有同步端点仍由 API 执行。

## 命令参数与退出码

- `--data-dir ABSOLUTE_PATH`：等价于该 Worker 进程的 `THESIS_DATA_DIR`；API 仍需独立设置同一路径。
- `--check`：打开仓储并执行启动对账，不领取作业；可能回收过期租约和重放既有 Outbox。
- `--once`：对账通过后最多领取一个当前可执行作业。若队列空闲或仅有未到重试时间的作业，输出 `IDLE` 并退出。
- `--worker-id NAME`：指定日志和租约所有者名称；不填则随机生成。执行凭证仍在每次领取时刷新。
- `--lease-seconds N`：租约秒数，默认 120、最小 10；适用于部署恢复时间调优和隔离故障演练。心跳间隔随租约变化；过短的租约更容易受数据库写锁等待或进程调度影响，正式部署先保留默认值。

`--check` 和 `--once` 不可同时使用。正常退出为 0；单次作业未成功为 1；参数错误、配置拒绝或对账未通过为 2。意外运行异常会使进程以非零状态退出，由部署进程管理器记录并处理。

`--check` 返回 `NEEDS_REPAIR` 时，使用现有 API 对账接口查看原因，修复后再启动 Worker。不能只删除作业或状态记录来绕过对账。

## 停止与恢复

控制台按 Ctrl+C，或在支持信号的部署环境发送 SIGTERM。Worker 停止领取新作业，保持当前作业的心跳，待它完成或正常失败后退出。它不会自动取消当前模型请求。

进程管理器的优雅停机期限应容纳当前作业；如果最终强杀，租约到期后由替代 Worker 恢复。默认租约为 120 秒，已保存检查点按现有恢复逻辑续作。窗口直接关闭和 Windows 强制结束进程属于强杀，不等同于可处理的 SIGTERM。

## 旧数据与交付边界

指定一个空数据目录会建立新的工作区，不会自动迁移原有 `backend/` 或旧启动目录中的数据库。后续已提供[存储迁移命令](存储迁移指南.md)，支持登记完整的当前表结构数据：先停掉所有写进程，明确来源清单，预检后复制并处理运行文件路径，再执行对账。旧内存中的模板/下载登记不会仅靠复制文件自动补齐，缺失时迁移会阻断。

本模式为单机、共享本地 SQLite 和文件目录的受控部署，不是多主机队列。PostgreSQL 版本化迁移、服务安装、自动备份、集中监控、网络故障与压力演练仍在路线图中。
