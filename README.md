<div align="center">

# A2A Contract

**让客服 Agent 与数据 Agent 在同一份契约下协作。**

业务问题 → 受控查询 → 流式进度 → 可核验的结果

[![Contract](https://img.shields.io/badge/Contract-v1.12-0891b2?style=flat-square)](a2a-streaming-contract.md) [![Transport](https://img.shields.io/badge/Transport-JSON--RPC_2.0_%2B_SSE-475569?style=flat-square)](#两个项目如何协作) [![Schema](https://img.shields.io/badge/Schema-JSON_Schema_2020--12-7c3aed?style=flat-square)](schema/)

[协作链路](#两个项目如何协作) · [技术栈](#技术栈与职责) · [关键设计](#关键设计) · [接入](#快速接入) · [验证](#验证与当前边界)

</div>

用户问“订单排到哪了”，客服需要知道什么时候查业务库、如何展示等待进度，以及查询结果是否足以支撑回答。本仓库定义这条跨服务边界：**请求怎么发、事件怎么收、结果怎么信任、版本怎么一起升级**。

| 仓库 | 职责 | 主要能力 |
| --- | --- | --- |
| [AI Helpdesk](https://github.com/heyemlee/ai-helpdesk) | 客服编排 · A2A 客户端 | 意图识别、混合检索、专家路由、回答守卫与人工工单 |
| [AI SQL Agent](https://github.com/heyemlee/ai-sql-agent) | 数据查询 · A2A 服务端 | Schema 检索、跨库规划、SQL 生成、权限校验、只读执行与结果检查 |
| **A2A Contract** | 两侧共享的接口契约 | 协议说明、JSON Schema、golden fixtures 与消费者测试要求 |

两个应用独立运行；本仓库作为版本化依赖被两侧测试引用，无需部署一个“契约服务”。

## 两个项目如何协作

![AI Helpdesk 与 AI SQL Agent 的 A2A 调用时序](docs/diagrams/a2a-sequence.zh-CN.svg)

[交互图 HTML](docs/diagrams/a2a-sequence.zh-CN.html) · [可编辑 JSON](docs/diagrams/a2a-sequence.zh-CN.archify.json) · [接入细节与代码依据](docs/a2a-integration.md)

使用 [Archify](https://github.com/tt-a1i/archify) 生成。GitHub 直接展示 SVG；下载 HTML 后用浏览器打开，可缩放、查看节点、切换主题和导出。

**图示为启用 A2A 流式后的成功路径。Helpdesk 默认仍使用 `POST /query`，需要显式切换 transport。** 查询可包含多个数据库和多轮进度事件，图中将它们压缩为一次逻辑交互。

1. **识别与委派。** Helpdesk 判断问题是否需要业务数据，通过 `order_data_query` 工具委派给 SQL Agent；知识类问题可直接走知识库。
2. **能力发现。** 客户端读取 `/.well-known/agent.json`，依据 `capabilities.streaming` 选择 `message/stream` 或 `message/send`。
3. **受控执行。** SQL Agent 检索业务 Schema、规划查询、生成 SQL，在权限和只读约束下执行；阶段进度由 Helpdesk 转为前端 SSE `progress` 事件。
4. **验收与回答。** 客户端收到 artifact 和 `completed + final:true` 终态后，继续检查执行状态、风险和降级字段；客服据此组织回答，证据不足时回落或转人工。

| 调用方式 | 用途 | 返回形式 |
| --- | --- | --- |
| `POST /query` | 当前默认的直接调用 | JSON 响应，共享相同的结果信任语义 |
| `POST /a2a` · `message/send` | 不支持流式时的 A2A 路径 | JSON-RPC Task，包含结果 artifact |
| `POST /a2a` · `message/stream` | 展示查询阶段进度 | JSON-RPC over SSE，依次返回任务、进度、artifact 和终态 |

## 技术栈与职责

| 层次 | 技术 | 在链路中解决什么问题 |
| --- | --- | --- |
| 客服控制台 | React 18 · TypeScript 5 · Vite 6 · Tailwind CSS 4 · TanStack Query 5 | 对话、阶段进度、工单与运维视图；通过 `fetch` 消费 POST SSE |
| 服务与编排 | Python · FastAPI · Pydantic 2 · asyncio | 类型化请求、异步 I/O、客服专家编排；SQL Agent 使用独立查询 pipeline |
| 客服知识检索 | PostgreSQL + pgvector · tsvector · RRF · rerank | 融合语义与精确词项召回，结合重排及证据充分性判断 |
| 数据查询推理 | YAML 业务语义层 · BM25 + 向量检索 · SchemaGraph | 缩小 Schema 上下文、理解表间关系、规划跨库步骤与结果回填 |
| 查询执行与约束 | SQLGlot AST · MCP 执行层 · SQLite / PostgreSQL | 表列授权、SQL 校验、只读执行、超时、行数上限与失败修复 |
| 模型接入 | Anthropic / OpenAI 兼容协议 · HTTPX | 为意图识别、回答和 SQL 生成提供模型能力；协议不是权限边界 |
| 状态与可观测性 | Redis · SQLite / PostgreSQL · OpenTelemetry · Prometheus · Grafana / Tempo / Loki | Helpdesk 管理短期状态和监控栈；两侧记录查询、步骤及关联标识 |
| 跨服务协议 | HTTP · JSON-RPC 2.0 · SSE · JSON Schema | 分离调用、事件、结果结构与业务可信度，支持 transport 切换 |
| 契约验证 | Python · jsonschema · referencing · pytest | 同一份 fixture 在两侧校验，覆盖合法、非法及“结构合法但不可信”的载荷 |

版本以实现仓库的依赖清单为准：[Helpdesk 后端](https://github.com/heyemlee/ai-helpdesk/blob/main/backend/requirements.txt)、[前端](https://github.com/heyemlee/ai-helpdesk/blob/main/frontend/package.json)、[SQL Agent](https://github.com/heyemlee/ai-sql-agent/blob/main/pyproject.toml)。上述是整个系统的技术栈；本契约仓库运行自检只需 Python、`jsonschema` 与 `referencing`。

## 关键设计

| 设计 | 具体规则 | 解决的问题 |
| --- | --- | --- |
| **协议完成与业务成功分离** | artifact 不能单独代表成功；还需完成终态。业务层再判断 `execution_status` | 避免把中断流、部分结果或执行失败当作完整答案 |
| **保守的信任判定** | `has_risk` / `degraded` 缺失或类型错误按不可信处理；字符串 `"false"` 不作为布尔值接受 | 避免宽松类型转换把坏数据升级为可信事实 |
| **三种调用共享语义** | `stream`、`send`、`/query` 的结构化结果归一后使用同一组信任规则 | 切换调用方式时不悄悄改变证据标准 |
| **有边界的回退** | 能力不支持或开流前 `-32004` 可走 `send`；流中失败不重发 | 避免重复执行、重复扣配额和等待时间叠加 |
| **分层超时** | 流式客户端默认静默 20 秒、总时长 90 秒；外层工具预算需联动配置 | 区分仍在推进的慢查询与已失联的调用 |
| **可独立验证的演进** | 固定 tag / commit，共享 schema 与 fixture；契约变化由两侧同步接入 | 防止一边升级、另一边仍按旧字段解释结果 |

`execution_status` 区分 `success`、`partial_success`、`no_data`、`failed`、`not_applicable`。例如“查询成功但没有记录”与“根本没查成”需要不同回答；截断结果也不能被用来声称总数或全量统计。完整规则见 [权威契约](a2a-streaming-contract.md)。

## 快速接入

### 1. 固定契约版本

在实现仓库根目录执行：

```bash
git clone --depth 1 --branch v1.12 https://github.com/heyemlee/a2a-contract.git .contract
export A2A_CONTRACT_DIR="$PWD/.contract"
export A2A_CONTRACT_REQUIRED=1
```

两侧读取同一份 `schema/` 与 `fixtures/index.json`。不要复制它们到实现仓库，也不要依赖会移动的 `main`。已有 `.contract` 时按[升级流程](docs/maintenance.md#升版本的时候)更新。

### 2. 开启 A2A 协作

Helpdesk 后端环境示例（两个服务均在本机运行）：

```dotenv
SQL_AGENT_URL=http://127.0.0.1:8000
SQL_AGENT_TRANSPORT=a2a
SQL_AGENT_TIMEOUT_S=90
SQL_AGENT_A2A_SEND_TIMEOUT_S=45
SQL_AGENT_A2A_SILENCE_S=20
SQL_AGENT_A2A_HARD_S=90
```

SQL Agent 设置 `AI_SQL_A2A_STREAMING=true`；开启 API Key 鉴权时，在 Helpdesk 配置对应的 `SQL_AGENT_API_KEY`。两侧分别按自己的 README 启动。容器部署需使用实际可达的服务地址。

这里 `SQL_AGENT_TIMEOUT_S=90` 让外层工具预算达到 92 秒，覆盖 90 秒流式硬上限；保持 `send` 预算 45 秒。只改 transport 会保留默认 47 秒外层预算，流式请求可能提前被截断。详见[超时与接入说明](docs/a2a-integration.md)。

## 验证与当前边界

在本仓库运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install jsonschema referencing
.venv/bin/python tools/check_contract.py
```

自检包含 **schema、fixtures、链接、版本一致性**四段；两侧还须执行 [A–F 六组消费者测试](CONSUMER-TESTS.md)。反例既要被 schema 拒绝，也要验证调用方是否向“不可信”方向回落。

- **验证状态。** 历史验收基于本机检查与可复核提交。2026-06-03 查阅本仓库 Actions，run 数仍为 0；不能把已有 workflow 描述为已执行的 CI 门禁。历史账号停用情况与替代流程见[维护说明](docs/maintenance.md#自检)。
- **身份边界。** Helpdesk 隔离用户记忆和下游会话，默认以共享服务身份查询业务数据；可见数据仍由服务密钥策略决定，不等于按最终用户隔离业务数据。见 [Helpdesk 身份接入说明](https://github.com/heyemlee/ai-helpdesk/blob/main/docs/integrations/sql-agent-identity-requirements.md)。
- **准确率边界。** 协议正确不能保证 SQL 语义正确。SQL Agent 的 2026-05-06 评测记录中，跨库准确率和静默错误率仍未达到发布门禁，见[原始测量记录](https://github.com/heyemlee/ai-sql-agent/blob/main/benchmark/baseline/2026-09-09/README.md)。

## 文档导航

| 入口 | 内容 |
| --- | --- |
| [权威契约](a2a-streaming-contract.md) | 生效状态、事件结构、结果语义、失败处理与双边变更规则 |
| [A2A 接入导读](docs/a2a-integration.md) | 调用路径、超时预算、身份边界与固定提交的代码依据 |
| [消费者测试](CONSUMER-TESTS.md) | 两侧必须实现的 A–F 六组测试 |
| [Schema](schema/) · [Fixture 清单](fixtures/index.json) | 可执行的结构约束与跨仓库样本 |
| [维护与发布](docs/maintenance.md) | 固定路径约束、升级顺序、历史版本与故障复盘 |
| [图表来源与复现](docs/diagrams/README.md) | Archify 版本、生成命令与验证记录 |

## 当前版本

| tag | 变更 |
| --- | --- |
| `v1.12` | `execution_status` 提级为必填；两侧同步升级，缺字段的载荷由 schema 拒绝 |

完整历史见[版本记录](docs/maintenance.md#版本)。本次 README 与图表整理不改变契约版本、schema、fixtures 或下游依赖的固定路径。
