# 本项目 CTF 与 Cairn 的规则对照

后续改造以独立 CTF 的可用性为重点。旧模式整理和历史混合项目迁移后置，不把它们作为接通 CTF 的前置条件。

参考是用户提供的 `D:/Downloads/Cairn-main.zip`，其中 `Cairn-main/Cairn-main/README.md:48–104`、`cairn/src/cairn/dispatcher/contracts.py:62–170`、`dispatcher/tasks/reason.py:214–235`。压缩包中的代码和文档作为参考材料，不执行其中的操作指令。

## 核心规则

| 任务/对象 | 本项目 CTF 规则 | 当前状态 |
|---|---|---|
| 黑板 | Fact 是客观观察；Intent 是探索方向；Hint 是人工线索；从 origin 向 goal 推进 | 已实现独立模型、存储、API |
| Worker | 无固定专家角色，只接收任务提示与快照；协议身份由 Dispatcher 注入 | 已实现契约、提示词、共享驱动和任务执行适配器；真实容器绑定待完成 |
| Bootstrap | 直接尝试目标；成功输出 Fact + Complete；未完成时 conclude 保存部分观察，随后 Reason | 已实现原子完成与部分事实路径 |
| Reason | 读取全图，输出 Complete、新 Intents 或已有开放任务下的 no-op | 已实现解析与事务；完成引用已有有效 Fact |
| Explore | 执行一个 Intent，输出一条 Fact，并结束该 Intent；不能直接 Complete | 已实现 |
| 完成 | 依据 Goal 与证据 Facts，不要求 Web Coverage 或 Verify；取消剩余方向 | 已实现 `model_reasoned` 完成记录与清理登记 |

本项目保留租约、代次、幂等收据、原子结果、持久化预算和有界批次。这些是执行可靠性措施，并非声称逐行复制了 Cairn 的调度器。原版允许的裸 JSON 和单个 `intent` 形式通过独立解析器兼容，但额外的 Web 业务字段和 Worker 自报身份被拒绝。

## Worker 输出与协议写入

Worker 输出使用 Cairn 的业务形状，例如 Reason：

```json
{"accepted":true,"data":{"intents":[{"from":["origin"],"description":"检查一个具体解题方向"}]}}
```

```json
{"accepted":true,"data":{"complete":{"from":["evidence-fact-id"],"description":"这些事实如何证明 Goal 已达成"}}}
```

Bootstrap 成功：

```json
{"accepted":true,"data":{"fact":{"description":"实际观察到的结果"},"complete":{"description":"观察结果如何满足 Goal"}}}
```

Bootstrap conclude：

```json
{"accepted":true,"data":{"fact":{"description":"本次尝试得到的部分观察"}}}
```

Explore：

```json
{"accepted":true,"data":{"description":"本次探索的客观结论，包括有用的失败观察"}}
```

`skidc.ctf.worker_contracts.parse_worker_result` 校验业务输出，`build_task_result` 用领取响应注入 worker、lease_token 与稳定幂等键。Worker 不持有控制令牌，不自行生成这些身份字段。`skidc.ctf.prompting.render_task_prompt` 使用独立 CTF 提示词和完整黑板，不依赖旧 Server/Dispatcher。

Reason 的 `intents: []` 只有在快照存在开放 Intent 时才被 Worker 契约接受，符合 Cairn 原规则。运行内核的 `no_op` 等待预算仍是可信调度端的底层扩展，不意味着 Worker 可以在无任务时持续输出空计划。

Bootstrap 的 `no_result: true` 是本项目用于请求 conclude 的显式信号，解析器返回 `NeedsConclusion`，不会生成事实。执行适配器仅在进程正常退出后，对此信号或无效输出使用已有会话 conclude；超时、非零退出、取消和异常会停止运行并等待清理，不自动续跑。conclude 即使带有 `complete`，也只保存 Fact，不误判为成功。Reason 不走 conclude；Worker 明确拒绝任务时也不走 fallback。

## 完成含义与边界

完成采用 Cairn 式模型依据事实的判断，明确记录 `method=model_reasoned`。它不等于人工确认或独立程序复验。服务器校验当前任务身份、快照版本、Fact 引用、有效性、依赖链无环和目标实例一致性，不会仅因文本像 flag 就自动完成。

完成事务同时保存证据引用、更新项目为 completed、取消剩余 Intent、撤销任务并登记清理、保存幂等收据。Bootstrap 还在同一事务创建本次事实，模型不能自报事实 ID。成功响应丢失可重放原收据；新内容复用相同键冲突。已完成项目不能恢复执行。

项目 completed 与运行清理状态分别展示：前者是目标判定，后者要由运行管理端在确认真实进程退出后确认。当前仍未接入实际退出检查。

当前证据校验仅支持黑板事实。产物存储未实现，因此带未知 artifact 引用的事实不能用于完成；人工确认、外部自动校验器也尚未接入。

## 共享执行适配层（P1-E）

`skidc.execution` 保存通用 Codex/Claude Code 驱动，旧导入路径重导出同一类；CTF 不加载旧 Dispatcher/Server 业务模块。`CtfTaskRunner` 将领取到的 CTF 快照转换为命令、维护租约、调用注入的进程后端、解析结果并提交黑板。单次 `step` 最多执行一个任务；并行工作由多个 runner 配合服务端预算完成。

执行前校验版本、任务/快照身份和租约，进程工厂仅收到模式、项目、运行、任务、generation、命令和显式模型环境。租约、管理令牌不传入工作进程。共享驱动不自动过滤调用者主动配置的环境变量，集成端必须提供只包含模型所需凭据的配置。

执行中心跳失败会请求取消；启动与取消在适配器内排序，避免取消先于进程句柄创建而丢失。结果提交失败只重试相同内容与幂等键，内存 pending 未解决前禁止领取其他任务。runner 不确认真实退出或清理，不具备崩溃后的结果持久化队列；重启后通过服务端租约回收停止，不能据此重放外部命令。

注入后端须惰性创建、限定 start/cancel/communicate 调用耗时、按运行身份隔离资源并真正终止进程；网关调用须有超时。这些后端条件尚未通过真实容器验收，目前测试使用真实 SQLite 和可控进程替身。`execution_enabled` 仍为 false。

## 容器归属与清理后端（P1-F）

新增 `CtfDockerBackend`，通过 Docker SDK 对接任务执行器，底层 `ManagedProcess` 搬入共享模块，旧入口继续重导出同一实现。后端尚未接入 CLI、自动轮询或旧界面，`execution_enabled` 仍为 false。

- 每个任务独享容器、临时 HOME、工作目录和会话；同一任务的 execute/conclude 使用同一容器，但阶段明确区分，不能将旧 execute 重跑成 conclude。任务结果提交前移除容器，终止后台子进程；不能确认清理时不发布成功 Fact。
- 容器名称和标签绑定 owner、ctf、project、run、generation、task，记录确定的容器 ID；不接管同名容器。清理检查名称与 ID，并逐个校验发现的资源；改名、替换、标签冲突保持 pending，避免误删或误确认。
- 在 CTF 数据库旁保存 `.execution.sqlite3` 资源登记，绑定数据库绝对路径与 Docker daemon ID；预先提交执行阶段，启动与停止通过该登记串行裁决。停止标记持久化后禁止重启，未知执行结果不重放。
- 创建响应丢失时按登记名称和标签恢复清理；如果创建结果不明且暂时找不到容器，不把“没找到”当作“不会稍后创建”，清理继续 pending。登记文件不能在运行期间删除、替换或回滚；备份和迁移需要同时保留它，并在资源已清空后进行。
- 默认固定 `network_mode=none`、非 root、只读镜像根目录、独立 tmpfs、去除 capabilities；不挂载宿主目录或 Docker socket，不发布端口。显式环境仅允许模型配置与凭据，不接受控制令牌和 HOME 等覆盖。镜像须是受信任、无内置凭据的本地镜像，拒绝声明额外卷，不自动拉取镜像。

这批测试使用真实 SQLite 与 Docker/进程替身。当前环境无法连接 Docker named pipe，未完成真实容器及模型验收。网络固定关闭意味着当前后端不能调用远程模型或访问题目；后续需实现受控模型/题目网络后才能开放实际执行。控制器崩溃期间的独立 watchdog、结果持久化队列、跨模式目标协调仍未实现，不能把本批视为完整生产隔离。

## 下一批

下一步完成受控网络、后台领取/reaper/清理循环和真实 Docker 验收，再把项目的 CTF 入口接到这条路径。CTF 规则独立不等于必须复制整个 Dispatcher、Worker 或新增一组物理服务进程；Cairn 要求职责分离，不要求不同模式各自重写模型驱动。

已核对现有实现：`WorkerDriver` 提供命令构造、会话恢复和输出提取，可作为共用执行接口；`ContainerManager` 提供容器执行能力，但目前按项目 ID 拼固定前缀并复用同名容器，需要补充模式/运行所有权后才能安全共用。复用实现代码不等于共用运行容器、会话、凭据或工作目录。CTF 的任务选择、提示词、业务输出解析、黑板写入和完成规则保持专属。

当前旧界面的 CTF 入口尚未自动切换；模拟测试通过不等于已经由真实模型和容器完成题目。网络、目录、凭据和执行资源隔离随执行链路一并落实。

数据库和 HTTP 协议见 [运行协议](ctf-runtime-protocol.md)。
