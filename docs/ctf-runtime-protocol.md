# CTF 独立运行协议预览

本批提供数据库和 HTTP 层面的执行身份、租约、结果幂等、Cairn 式完成判定与停止清理协议，供模拟执行器集成。**尚没有启动真实 Worker 或容器的执行器。** `/health` 的 `execution_enabled` 始终为 `false`；不要把领取任务当作已经获得启动真实进程的完整授权。核心任务规则与输出示例见 [Cairn 规则对照](ctf-cairn-rules.md)。

## 启用方式

默认启动仍只开放项目创建、黑板读取、人工 Hint。显式提供三份不同的随机令牌文件后，才开放运行协议：

```sh
skidc-ctf serve --db-path ./data/ctf/ctf.db --token-file ./secrets/ctf-control --dispatcher-token-file ./secrets/ctf-dispatcher --runtime-token-file ./secrets/ctf-runtime
```

每份令牌至少 32 个 ASCII 字符，不复用 Web 凭据，不交给 Worker。默认只监听 `127.0.0.1:8001`。身份由 Bearer 令牌确定，不能在请求体中自报角色；`worker_instance_id` 是 Dispatcher 注入的实例关联标识，必须与对应的租约令牌一起使用。

| 身份 | 权限 |
|---|---|
| control | 创建/读取项目、Hint、开始/读取/停止运行 |
| dispatcher | 读取项目/黑板/运行、领取任务、心跳、结果提交 |
| runtime | 查询待清理操作、确认清理、回收过期租约 |

这三类凭据代表可信控制组件，不是多租户的用户账户授权系统。运行管理端必须在真实进程退出已得到确认后才能调用清理确认；本版本只验证调用身份与操作登记，不会自己连接 Docker 核实。

## 数据库升级

当前独立 CTF schema 为 4。启动时拒绝 schema 1/2/3，不能通过手动改版本号跳过检查。先停止使用旧文件的服务，再执行：

```sh
skidc-ctf upgrade-copy --source ./data/ctf/old.db --destination ./data/ctf/new-v4.db
```

该命令只读源文件，将其一致快照复制到一个新文件，保留原有项目、Fact/Intent/Hint 和修订号，并校验引用。schema 2/3 还保留历史运行、任务及幂等收据，schema 3 保留历史调度状态；必须先停止全部运行并确认清理，存在开放租约或待清理操作时拒绝升级。历史运行版本保持原值，恢复时创建新版运行与新代次。目标已经存在则拒绝；失败会删除本次新建的不完整目标。完成后使用新路径启动，不同时开放两份副本写入。源文件保留用于核对。这里只升级独立 CTF 库，**不支持迁移旧混合模式库，也没有自动改变旧项目执行权**。

## 运行与任务

以下路径均以 `/api/ctf/v1` 为前缀。

| 方法和路径 | 身份 | 请求/结果 |
|---|---|---|
| `POST /projects/{pid}/runs` | control | `idempotency_key`、`target_instance_id`；返回新 run_id、generation 和固定版本信息 |
| `GET /projects/{pid}/runs/{rid}` | control / dispatcher | 查询当前或历史运行状态 |
| `POST /projects/{pid}/runs/{rid}/stop` | control | 无请求体；撤销租约并登记清理，重复调用不会新增清理任务 |
| `POST /projects/{pid}/runs/{rid}/tasks/claim` | dispatcher | `kind`、`worker_instance_id`，Explore 还必须有 `intent_id` |
| `POST /projects/{pid}/runs/{rid}/tasks/claim-next` | dispatcher | 仅 `worker_instance_id`；由服务端选择任务，返回一致快照或等待/停止原因 |
| `POST /projects/{pid}/runs/{rid}/tasks/{tid}/heartbeat` | dispatcher | `worker_instance_id`、`lease_token` |
| `POST /projects/{pid}/runs/{rid}/tasks/{tid}/result` | dispatcher | 身份、幂等键及一种结果，见下文 |
| `GET /runtime/operations` | runtime | 返回持久化的待清理操作及其 project/run/generation |
| `POST /runtime/operations/{id}/confirm` | runtime | 确认该运行已清理；重复确认不会影响新运行 |
| `POST /runtime/reap-expired` | runtime | 撤销已过期任务所在运行并登记清理 |

开始运行时固定 engine/schema/prompt 版本、配置摘要和目标实例。一个项目同时只有一轮当前运行，同一个 CTF 数据库中的目标实例不能被两个运行同时占用。**这不是跨 Web/CTF 的全局目标协调器**。恢复仍使用同一目标实例；目标重置应使用新的项目，不能沿用旧观察。

领取响应含任务 ID、run_id、generation、base_revision、lease_token 和服务端截止时间。租约为 30 秒，心跳仅在原租约仍有效时续期，不改变黑板修订号。令牌数据库只存哈希，不以 Worker 名字代替身份。领取响应丢失时不会恢复原令牌，也不会直接重新执行；等待过期回收、确认清理后恢复。

Reason/Bootstrap 与本项目其他任务互斥；Explore 可以并发，但同一 Intent 不能被同时领取。启用 Bootstrap 的新项目可直接提交 Fact + Complete；若只获得部分观察，先提交 Fact，再进入 Reason。

## 有界调度（P1-C）

创建运行时传入 `scheduler: {}` 启用；省略或传 `null` 时仍为手动协议。调度策略固定进运行配置摘要，不能运行中修改。启用调度后，只能通过 `claim-next` 领取，手动 `claim` 返回 `scheduler_managed`，避免绕过预算。

```json
{"idempotency_key":"start-1","target_instance_id":"lab-1","scheduler":{"max_parallel":2,"batch_size":4,"max_tasks":64,"run_seconds":900,"batch_seconds":120,"no_progress_limit":3,"conflict_limit":3,"wake_seconds":10}}
```

这些值也是当前预览默认值：每项目最多并行 2 个 Explore，每批最多 4 个 Intent，每运行最多领取 64 次任务；运行期限 900 秒、批次期限 120 秒；连续无进展最多 3 次，连续 Reason 修订冲突最多 3 次，等待后每 10 秒可再次规划。它们不是经过负载测试的容量承诺，也不限制手动协议运行或另一项目的并发。

调度顺序是 Bootstrap（启用时）→ Reason → 一批 Explore → Reason。Reason 成功提交后固定本批 Intent 集合，按创建顺序选取尚未结束的方向；本批尚有任务未结束时不启动下一个 Reason，也不补入本批之外的 Intent。上一批完成后先重新规划，再派发下一批。

`claim-next` 请求只含 `worker_instance_id`，返回三种结果：

- `status=claimed`：含 `task` 租约和 `board` 黑板快照；任务选择、领取和快照读取在同一事务内，`task.base_revision == board.revision`。
- `status=waiting`：当前任务未结束或等待到期；`next_wakeup_at` 为服务端 Unix 时间，任务执行期间可为 null。
- `status=stopping`：达到预算或到期，含 `reason`；已持久化停止与清理操作，不再派发。

Reason 可以提交 `{"no_op":true}`。有未结束 Intent 时继续下一批；没有可探索方向时，不制造 Fact 或新 revision，而是保存等待时间与无进展计数。新 Hint 会提前唤醒，定时到期也允许再次规划。达到无进展上限则停止，等待操作人员处理。

批次、任务次数、重规划次数、等待时间均保存在数据库，服务重启不会重置。`GET .../runs/{rid}` 的 `scheduler` 字段显示策略和当前状态。心跳不能超过运行或本批截止时间；超时新结果被拒绝，原有成功收据仍可读取。`claim-next` 或 reaper 负责将到期运行置为停止；已完成批次不会因为调度端稍后才轮询而被错误判为批次超时。

当前仍需可信 Dispatcher 周期性调用领取接口，以及 runtime 端周期性调用 reaper。这里实现的是服务端调度协议，尚未启动后台轮询进程或真实 Worker；`execution_enabled` 仍为 false。

## 结果与重试

所有结果都由 Dispatcher 注入 `worker_instance_id`、`lease_token` 和 `idempotency_key`。不要将这些执行身份交给模型生成。业务结果只允许下列一种：

```json
{"intents":[{"from":["origin"],"description":"检查题目入口"}]}
```

```json
{"description":"本次探索得到的客观观察"}
```

```json
{"error":"执行状态不明，需清理后人工处理"}
```

第一种用于 Reason，第二种用于 Bootstrap/Explore，第三种适用于所有任务。启用有界调度的 Reason 还支持 `{"no_op":true}`。Web 字段、未绑定的 artifact 引用及多个结果分支同时提交都会被拒绝。完成分支见下文。

Reason 提交必须匹配领取时的黑板 revision，来源 Fact 必须存在于本项目、有效且不包含 goal。期间新增 Hint 不会写入旧计划：有界调度返回 HTTP 200 的 `status=rejected, code=revision_conflict` 收据，结束这次只读 Reason 并消耗冲突预算；后续 `claim-next` 获取新快照重规划，达到上限停止。重复提交返回原收据，不重复扣预算。手动协议仍返回 HTTP 409，调用方需停止清理后恢复。调用方必须检查结果体 status，不能把 HTTP 200 一律视为业务结果已接受。

Explore 的新 Fact、Intent 终态和幂等收据在同一事务写入。相同键和内容返回原结果，包括原租约过期或运行停止后的重试；不同内容复用该键返回 `idempotency_conflict`。相同 run 下不同任务也要使用不同键。读取原收据仍须通过 Dispatcher 身份和原 task/worker/token 校验，收据不会绕过身份认证。

失败只记录诊断并停止运行，不编造 Fact、不自动重放外部命令。提交响应丢失时先重试同一个键，不产生第二份 Fact。数据库去重不能保证外部命令“恰好执行一次”。

## Cairn 完成结果（P1-D）

同一个带租约的任务结果接口额外接受两种互斥分支。Reason 引用已有事实：

```json
{"complete":{"from":["fact-id"],"description":"这些事实如何证明 Goal 已达成"}}
```

Bootstrap 同时写入新事实并完成：

```json
{"bootstrap_complete":{"fact_description":"本次观察到的证据","complete_description":"证据如何满足 Goal"}}
```

调用方仍须带 worker、lease_token 和 idempotency_key。Explore 不接受这两种完成分支。完成必须匹配领取时的 revision；Bootstrap 期间 Hint 改变则拒绝直接完成，可以用同一有效任务提交部分观察，再由新 Reason 判断。

服务器检查证据属于本项目、非 goal、有效且具有同目标运行出处，递归检查事实依赖（带循环检测）；当前未实现的 artifact 引用拒绝作为完成证据。完成、Bootstrap 新 Fact、剩余 Intent 取消、清理操作和收据同一事务提交。

成功结果为 `status=completed`，含 completion_id 和 revision；Bootstrap 另含 fact_id。黑板新增 `completion`，包含 `from`、`to=goal`、说明、来源任务/运行、revision、goal_version 和 `method=model_reasoned`。没有完成时该字段为 null。

这是 Cairn 式模型依据事实的目标判断，不是独立环境校验。完成后项目状态为 completed，运行仍需要确认清理；原收据可以重放，新的任务写入和恢复请求被拒绝。人工确认及外部校验器仍待接入。

## 停止与未完成边界

停止事务将运行置为 `stopping`、清理置为 `pending`，撤销本轮所有任务租约并登记 stop 操作。API 重启后仍能查询这些操作；启动时还会回收已到期任务。没有后台扫描线程，集成端必须周期性调用 reaper。

清理确认之前禁止恢复。确认之后新运行分配不同的 run_id 和更高 generation；同名 Worker 的旧令牌也不能使用。版本不匹配的运行不能继续工作或恢复，但仍能停止并清理。

P1-E 新增 `CtfTaskRunner`，已通过共享驱动实现快照到命令、同会话 conclude、心跳取消及同键提交重试；旧驱动导入路径仍指向同一份实现。执行后端通过 `process_factory(scope, argv, env)` 注入，当前尚未绑定真实容器，也未开放实际执行 CLI。详见 [Cairn 规则与执行边界](ctf-cairn-rules.md)。

P1-F 新增本地 `CtfDockerBackend` 与独立资源登记文件，实现任务容器归属校验、持久化启动/停止裁决、明确的 execute/conclude 阶段及任务结果提交前的容器清理。`cleanup_operation` 必须验证本轮所有已登记及发现的容器已移除才确认 API 清理；名称/ID 冲突或创建结果不明则保留 pending。此后端默认网络关闭，尚未通过真实 Docker 验收或接入服务启动入口。

尚未实现：控制器之外的容器 watchdog、自动领取与 reaper/清理轮询、受控模型/题目网络、真实容器中的会话恢复验收、证据产物提交与校验、人工/外部完成候选确认、跨模式目标协调、历史混合项目迁移。当前测试验证事务/API 和注入 Docker/进程替身下的执行流程，不等于这些运行边界已经验收。后续优先接通 CTF 实际执行，旧模式整理和迁移后置。
