# A2A 流式契约：`message/stream`

> 状态：**草案 v0.1，待与调用方（ai-helpdesk）对齐**。本文只定义契约，不含实现。
> 对齐通过之后再动代码，改动清单见 §8。
>
> 本文的"我方"= ai-sql-agent（A2A 服务端），"调用方"= ai-helpdesk（A2A 客户端）。

---

## 1. 前提：调用方那边已经成立的事实

这三条是调用方已经做完并验证过的，本契约**基于**它们，不重新讨论：

| # | 事实 | 对契约的约束 |
| --- | --- | --- |
| ① | 调用方已有 SSE 心跳（演示 1s，默认 15s），对 60s 代理超时有 4 倍余量 | **我方不发心跳、不发空事件**。见 §3.4 |
| ② | 调用方已有 progress 事件通道，形态是「阶段标签 + 可选文案」 | 我方事件必须能直接映射过去，不要求它重写。见 §4.5 |
| ③ | 消费端是 `httpx.AsyncClient`，超时 **25 秒**，任何失败静默回落 | 不引入新依赖/新协议栈；中途失败必须能干净回落；25s 是总预算。见 §5 |

调用方当前实测时序（委派给我方的那段是静默期）：

```
[0.00s] event: progress   ← 检索知识库
[0.40s] event: progress   ← 正在查 ERP 订单库
[1.40s] : ping            ┐
[2.40s] : ping            ├ 委派给我方的静默期，今天这里是零字节
[3.40s] : ping            ┘
[3.90s] event: meta / event: routing
[6.10s] event: delta / event: result
```

**本契约要填的就是那段静默期。** 不是延长 25s 预算，是把预算填满。

---

## 2. 为什么值得做（我方这侧的数据）

审计库里 82 次真实模型调用（非 Mock）的实测：

| 路由 | 次数 | 平均耗时 |
| --- | --- | --- |
| `database_query`（查库） | 7 | **17.7s** |
| `data_qa`（对话） | 75 | 8.6s |

全量 p50 6.6s / p90 17.7s / max 68.3s。

也就是说：**查库路径的典型耗时（17.7s）已经吃掉调用方 25s 预算的 71%**，而这段时间调用方那边是零字节。这是两边加起来最值得补的一处。

同时也说明一件不舒服的事：**p90 就已经 17.7s，max 68s——有相当比例的查询本来就超出 25s 预算。** 流式不解决这个，只是让超时之前的等待有内容。§5.4 说明超时之后会发生什么。

---

## 3. 传输层

### 3.1 端点与请求

沿用现有端点，只增加一个 method。**不新开路径、不新开端口、不换协议。**

```http
POST /a2a HTTP/1.1
Content-Type: application/json
Accept: text/event-stream
X-API-Key: <同 message/send 的那把 key>
X-Trace-Id: <可选，调用方的链路 ID>

{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "message/stream",
  "params": {
    "message": {
      "kind": "message",
      "role": "user",
      "messageId": "...",
      "contextId": "<可选，会话 ID>",
      "parts": [{"kind": "text", "text": "SO-2024-001 现在什么状态"}],
      "metadata": {"user_id": "<可选>"}
    }
  }
}
```

`params.message` 的解析规则与 `message/send` **完全一致**（`parts` 里的 text 拼接、`contextId` 当会话、`metadata.user_id` 当身份），此处不重复定义。

成功时响应：

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Trace-Id: <本次链路 ID>
```

httpx 侧就是 `client.stream("POST", url, json=..., headers=...)` 然后 `aiter_lines()`，不需要任何新依赖。

### 3.2 鉴权

**与 `message/send` 同一把 key、同一套拒绝逻辑**（`require_api_key`）。A2A 不是旁路，这条不变。

关键约定：**鉴权失败、限流、参数错误一律发生在流打开之前**，返回普通 JSON 响应，不是 SSE：

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"jsonrpc":"2.0","id":"req-1","error":{"code":-32600,"message":"..."}}
```

> **调用方要注意的一点：** 拿到响应后先看 `Content-Type`，是 `application/json` 就按错误处理并回落，不要直接进 SSE 解析循环。这是刻意设计——你不该为了知道"我没通过鉴权"而去解析一个事件流。

限流（429）同理，见 §5.5。

### 3.3 trace_id

trace_id 在流式下走三个地方，值完全相同：

| 位置 | 说明 |
| --- | --- |
| 请求头 `X-Trace-Id` | 调用方可透传自己的链路 ID，我方原样沿用 |
| 响应头 `X-Trace-Id` | SSE 的响应头在正文之前发出，所以这个头照常可用 |
| **每一个事件的 `metadata.trace_id`** | 新增。见下 |

第三条是为流式专门加的：SSE 消费循环里通常只留 payload、不留响应头，把 trace_id 放进每个事件，调用方随手记一条日志就能和我方服务端日志对上，不用回头翻 response 对象。

排查时：拿这个 trace_id 到我方日志里检索，能取到完整的 stage 时序、SQL、命中表、token 用量。

### 3.4 不做心跳（明确）

**我方不发 `: ping`、不发空事件、不发任何无语义的保活帧。**

理由，按事实①：

1. 调用方已有 15s 心跳，存活性在**它对它自己客户端**那一段已经解决；
2. 我方到调用方这一段的连接寿命上限就是调用方的 25s 预算，**不存在比 25s 更短的代理空闲超时**（真有的话调用方今天的 `message/send` 早就在 17.7s 那档挂了）；
3. 进度事件本身就是流量。查库路径上相邻两个 stage 的最大间隔远小于 25s。

所以保活在这条链路上是重复发明。**契约里不定义 keep-alive，调用方也不要为它写解析分支。**

---

## 4. 事件

### 4.1 信封

每个 SSE `data:` 承载一个完整的 JSON-RPC 2.0 响应，`id` 与请求一致（A2A 规范形态）：

```
data: {"jsonrpc":"2.0","id":"req-1","result":{ ...事件... }}

```

事件按 `result.kind` 分三类：`task`（首帧快照）、`status-update`（进度与终态）、`artifact-update`（结果载荷）。

### 4.2 事件顺序（**保证**）

```
1×  task              首帧：taskId / contextId，state=submitted
N×  status-update     进度，final=false，state=working
1×  artifact-update   结果载荷，lastChunk=true
1×  status-update     终态，final=true，state=completed|failed
```

保证的部分：
- 首帧一定是 `task`；
- 终态事件一定是最后一个，且**有且只有一个**；
- `artifact-update` 一定在终态事件之前；
- 进度事件之间保持 pipeline 的真实先后顺序。

不保证的部分：进度事件的**数量和种类**。同一个问题两次跑，走没走短路径、修没修 SQL，进度事件都会不一样。**调用方不要对事件条数做任何假设，尤其不要用条数判断进度百分比。**

### 4.3 进度事件

```json
{
  "kind": "status-update",
  "taskId": "…",
  "contextId": "…",
  "final": false,
  "status": {
    "state": "working",
    "timestamp": "2026-08-25T12:00:00.400Z",
    "message": {
      "kind": "message", "role": "agent", "messageId": "…",
      "taskId": "…", "contextId": "…",
      "parts": [{"kind": "text", "text": "正在查 ERP 订单库"}]
    }
  },
  "metadata": {
    "stage": "execution",
    "step": 1,
    "database": "erp_db",
    "trace_id": "e620e55f2e294505"
  }
}
```

对应事实②要的三样东西：

| 调用方需要 | 在哪 |
| --- | --- |
| 稳定的机器可读 stage 标识 | `metadata.stage` ← **这是契约面，见 §4.5** |
| 可选的人类可读描述 | `status.message.parts[0].text` |
| 是否为终态 | `final`（进度事件恒为 `false`） |

`metadata` 放在**事件根**而不是 `status.message.metadata` 里：调用方读一跳就拿到，不用 `status → message → metadata` 走三跳。这是 A2A 允许的扩展位。

`metadata` 里除 `stage`/`trace_id` 外都是可选字段，**调用方必须容忍缺失**（例如 `step`/`database` 只在按步骤重复的 stage 上出现）。

### 4.4 结果载荷与终态

`artifact-update` 的 `artifact` 与今天 `message/send` 返回的 Task 里那个 **完全同构**——文本 part（答案）+ data part（`route` / `confidence` / `queried_database` / `has_risk` / `degraded` / `degrade_reason` / `selected_databases` / `trace_id` / `steps[]`）。

**这是刻意的：调用方走 send 还是走 stream，能做的信任判断必须一模一样。** 不存在"流式拿到的信息更少/更多"。

终态事件：

```json
{
  "kind": "status-update", "taskId": "…", "contextId": "…",
  "final": true,
  "status": {"state": "completed", "timestamp": "…"},
  "metadata": {"trace_id": "…"}
}
```

`state` 取值与今天 `_task_from_query` 的判定**保持一致**，不新增语义：

| state | 含义 |
| --- | --- |
| `completed` | 所有步骤成功（或走的是对话路径） |
| `failed` | 任一步骤失败 / 执行出错 / 被拒 |

> `degraded=true`（模型不可用、走了历史 SQL 重放）**仍然是 `completed`**，降级标记在 artifact 的 data part 里。这与 `message/send` 今天的行为一致，不要在流式下改判。

### 4.5 stage 映射表 ← **本文核心**

**契约面是下表的 `stage` 值，不是我方内部的 stage 名。** 内部重构（比如把 `sql_generation` 改名）不得改变这一列；这一列要改就是一次契约变更，走 §6。

| 我方 `metadata.stage` | 出现时机 | 会重复？ | 附带字段 | 我方默认文案 | 调用方 progress 建议 |
| --- | --- | --- | --- | --- | --- |
| `normalization` | 仅当问题被改写（代词消解 / 相对时间→绝对区间） | 否 | `original`, `normalized` | 正在理解问题 | **建议不展示**（内部动作，用户看不出差别） |
| `routing` | 每次 | 否 | `route`, `confidence` | 正在判断问题类型 | 可对应你那条 `event: routing` |
| `retrieval` | 仅查库路径 | 否 | `databases[]`, `table_count` | 正在检索知识库 | ← 对应你 `[0.00s]` 那条 |
| `planning` | 仅查库路径 | 否 | `steps`, `short_path` | 正在规划查询步骤 | 展示 |
| `generation` | 每个查询步骤 | **是**（按 `step`） | `step`, `database`, `dialect` | 正在生成查询（ERP 订单库） | 展示 |
| `execution` | 每个查询步骤 | **是** | `step`, `database` | 正在查 ERP 订单库 | ← 对应你 `[0.40s]` 那条 |
| `repair` | 仅 SQL 出错时 | **是** | `step`, `database`, `attempt` | 查询出错，正在重试 | 展示（这是最值得让用户看到的一条） |
| `validation` | 每个成功步骤 | **是** | `step`, `findings` | 正在校验结果 | 建议不展示 |
| `answering` | 仅对话路径 | 否 | — | 正在组织回答 | 展示 |

补充说明：

- **`database` 的取值**是我方的库标识：`erp_db` / `mes_db` / `pm_db` / `wms_db`。调用方若要自己造文案（比如把 `erp_db` 显示成"ERP 订单库"），用这个字段做映射，**不要去解析我方文案字符串**。
- **`step` 从 1 开始**，跨库查询会有多步。
- **内部有而契约不暴露的 stage**：`memory_context`（会话记忆读取，纯内部管道，对用户没有展示价值）。刻意不发，避免契约面无谓变大。
- **`normalization` 在我方今天不是一个真正的 stage**（它是 `text2sql_pipeline.py:216` 一条裸 `log_event`，且只在问题被改写时才记）。要发这个事件需要先把它变成真 stage，见 §8。

---

## 5. 失败与回落（25s 预算）

### 5.1 唯一的成功判据

> **收到 `final:true` 且 `state:"completed"` 的终态事件 ⟺ 成功。其余一切情况都回落。**

这条是硬规则，用来兑现事实③里的"不能留下半个结果被当成成功"。

具体地，以下**都不是**成功，调用方必须回落到静默降级（今天的"请提供订单号"）：

| 情况 | 判据 |
| --- | --- |
| 流正常结束但没有终态事件 | 迭代器耗尽 且 未见 `final:true` |
| 终态事件是 `state:"failed"` | `final:true` + `failed` |
| 连接中断 / 协议错 / JSON 解析失败 | httpx 抛异常 |
| 25s 预算耗尽 | 调用方自己的超时 |
| 响应 `Content-Type` 是 `application/json` | 鉴权/限流/参数错，见 §3.2 |

**特别地：只收到 `artifact-update`、没收到终态事件，也算失败。** artifact 在正常情况下只比终态事件早几毫秒，按严格规则处理几乎不损失可用结果，但能彻底堵死"半个结果被当成成功"这条路。

### 5.2 流打开之后才出错怎么办

我方**不会**靠断开连接来表示失败。任何在流中途发生的错误，都会补一个终态事件再关闭：

```json
{"kind":"status-update","final":true,
 "status":{"state":"failed","message":{...部分文本，可能为空...}},
 "metadata":{"trace_id":"…","error":"查询执行失败"}}
```

这样调用方永远走同一条判定路径（§5.1），不需要区分"优雅失败"和"连接断了"。

### 5.3 25s 是预算，不是可以商量的下限

我方**不会**为了塞进 25s 而截断查询或降低质量。流式在这里的作用只有一个：把等待变成可见的进度。查询该多久还是多久。

### 5.4 超时之后我方会发生什么（**重要，请调用方确认能接受**）

调用方 25s 超时并断开连接后：

- 我方**不会**中止查询。整条 pipeline 是同步的，没有取消点；
- SQL 会跑完，**审计记录照常写入**，**每日配额照常计入**，token 照常消耗；
- 只是结果没人接收了。

含义：**反复超时会静默烧配额。** 如果调用方在超时后有重试逻辑，请特别注意——同一个问题重试 3 次 = 我方 3 条审计 + 3 份配额。这一条今天在 `message/send` 上就已经成立，流式没有改变它，但值得在契约里写明。

### 5.5 限流与配额

**一次 `message/stream` = 一次 `/query`**：一个令牌、一条审计、一份配额。与 `message/send` 完全等价，不打折也不加倍。

限流命中时在流打开之前返回 429（含 `Retry-After` 头），走 §3.2 的 JSON 错误路径。

---

## 6. 向后兼容

### 6.1 `capabilities.streaming` 翻 true 之后，老客户端怎么办

**`message/send` 永久保留，不弃用、不改形状、不降优先级。** 两条路走的是同一个 handler、同一套鉴权限流审计，只是出口不同。

| 客户端类型 | 行为 |
| --- | --- |
| 不读 Agent Card，硬编码 `message/send` | 完全不受影响 |
| 读 Card 但只实现 send | 完全不受影响（`streaming:true` 只是"另有一条路"，不是"这条路没了"） |
| 读 Card 且实现 stream | 走流式 |
| 通用 A2A 客户端库，见 `streaming:true` 就自动优先 stream | 走流式，且能正确解析——事件形态是标准 A2A |

**不做版本协商**：A2A 没有 per-method 版本位，加一层自定义协商只会让两边都变复杂。Card 的 `version` 从 `1.0.0` 提到 `1.1.0` 作为标记，`protocolVersion` 保持 `0.2`。

### 6.2 回滚

流式能力挂在一个开关上（建议 `AI_SQL_A2A_STREAMING`，默认开）：

- 关掉 → Card 的 `capabilities.streaming` 变回 `false`，`message/stream` 重新返回 `-32004`；
- **不需要重新部署，也不需要调用方配合**——调用方读到 `streaming:false` 或收到 `-32004` 就退回 `message/send`，那是它今天已有的行为。

请调用方确认：**读到 `-32004` 时能干净退回 send**，而不是当成硬失败。这是回滚路径能不能用的前提。

---

## 7. 明确不承诺什么

写清楚比留白好——以下都是**刻意不做**，不是"还没做"：

| 能力 | 做不做 | 原因 |
| --- | --- | --- |
| **断线续传 / `Last-Event-ID`** | ❌ 不做 | 事件不带 `id:` 字段。续传要求服务端保留事件缓冲并支持按 offset 重放，而我方的查询是一次性的、不可重放的。断了就重发请求。 |
| **`tasks/resubscribe`** | ❌ 不做 | 继续返回 `-32004`。同上：没有可重新订阅的持久事件流。 |
| **`tasks/cancel`** | ❌ 不做 | 继续返回 `-32004`。pipeline 是同步的，没有取消点；假装支持会得到一个"返回成功但活还在跑"的假接口，比明说不支持更糟。见 §5.4。 |
| **答案 token 级增量（delta）** | ❌ v1 不做 | 终态之前不含任何答案内容。查库路径的答案是 SQL 结果拼出来的，本来就没有 token 流；对话路径倒是可以（`transport.py` 已有 `chat_stream`），但为半条路径引入 delta 语义不划算。见 §9。 |
| **push notifications** | ❌ 不做 | Card 保持 `pushNotifications:false`。 |
| **进度百分比 / ETA** | ❌ 不做 | 事件数量本身不稳定（§4.2），任何百分比都是编的。 |
| **事件重投递 / at-least-once** | ❌ 不做 | 尽力而为。丢了就是丢了，靠 §5.1 的终态判据兜底。 |
| **`tasks/get` 在多副本下可靠** | ⚠️ 已知缺陷 | 任务表是进程内的，多副本下 `tasks/get` 会大概率 `-32001`。流式不改变这一点。**建议调用方不要依赖 `tasks/get`**，终态事件里已经有全部结果。 |

---

## 8. 落地要改的清单

对齐通过后按此执行。**本文档不含实现，以下只是范围界定。**

### 8.1 措辞：三处"秒级同步"的说法要改

这三处现在都在明说"不做流式"，翻 `streaming:true` 之前必须一起改，否则文档和 Card 自相矛盾：

| 位置 | 现在的话 |
| --- | --- |
| `ai_sql_a2a/__init__.py:14-15` | 「不做 message/stream、tasks/cancel、push notifications：一次订单查询是**秒级同步**操作，为它建流式通道和回调机制是把协议表面积当成目标本身。」 |
| `README.md:179` | 「Streaming and push notifications are declared unsupported in the Card; **a lookup is a synchronous, seconds-scale call** and the protocol surface stays that small on purpose.」 |
| `README.zh-CN.md:179` | 「Card 里如实声明不支持流式和推送：一次查询是**秒级同步调用**，协议表面积刻意只有这么大。」 |

> 你只点了前两处，第三处是中文 README 的镜像段落，同一句话的翻译；两个 README 是互译关系，漏改一个就会出现"英文说支持、中文说不支持"。一并列出。
>
> 改写方向：不是简单删掉，而是换成**为什么现在做了**——p90 17.7s 的实测数据（§2）就是那个"原来的判断哪里错了"。`tasks/cancel` / push notifications 依然不做，那部分理由仍然成立，要保留。

### 8.2 代码

| 位置 | 改什么 |
| --- | --- |
| `ai_sql_core/trace.py` 的 `stage()` | **进度事件的唯一钩子。** 加一个 ContextVar 事件汇：`stage()` 进出时向汇里推一条。pipeline 侧**零改动**——所有阶段本来就都穿过这一个上下文管理器。这是整个方案最省的地方。 |
| `ai_sql_pipeline/text2sql_pipeline.py:209-221` | `normalization` 目前是裸 `log_event` 且只在 `changed` 时记，要变成真 `stage()` 才能进事件流（§4.5 末条） |
| `ai_sql_api/app.py` | 把 `require_api_key` + `limiter.check` 提到流打开之前（§3.2 / §5.5）。同步 pipeline 跑在工作线程里，事件经队列喂给 async 生成器——`/query` 是同步 `def`，`service.run()` 阻塞，不要为此改成 async pipeline |
| `ai_sql_a2a/server.py:92-96` | Card：`capabilities.streaming` → 由开关决定；`version` → `1.1.0` |
| `ai_sql_a2a/server.py:296-299` | `message/stream` 移出 `-32004` 列表（`tasks/cancel`、`tasks/resubscribe` 留在里面） |
| `ai_sql_a2a/server.py` | 新增 stream handler：事件构造 + 顺序保证（§4.2）+ 中途失败补终态（§5.2） |
| `ai_sql_core/settings.py` | 新增 `AI_SQL_A2A_STREAMING` 开关（§6.2） |

### 8.3 测试

| 位置 | 改什么 |
| --- | --- |
| `tests/test_a2a_server.py:54-56` | 现在断言 `assertFalse(caps["streaming"])`，要跟着开关走 |
| `tests/test_a2a_server.py:165-168` | 现在断言 `message/stream` 返回 `-32004`，要移出该用例 |
| 新增 | 事件顺序保证（§4.2）、终态唯一性、中途失败补终态、开关关掉时退回 `-32004` |

### 8.4 容量（不改代码，但要知道）

`/query` 是同步 `def`，跑在 anyio 默认 **40** 线程的线程池里。一次查库 17.7s 就占住一个线程 17.7s → **单副本约 2.3 QPS 上限**。流式期间还额外占住一条 HTTP 连接。当前默认限流是 60 次/分/调用方（1 QPS），**3 个调用方跑满就能占满线程池**。这条今天就成立，流式让连接也一起占住，压测时按这个算。

---

## 9. 待调用方确认

1. **§5.4**：超时后我方不中止、照常计费计配额——能接受吗？你们超时后有重试吗？
2. **§6.2**：读到 `-32004` 时能干净退回 `message/send` 吗？这是回滚路径的前提。
3. **§4.5**：映射表里的 stage 集合够不够？有没有哪个你们其实不想要（少发少解析），或者缺了哪个？
4. **§4.5 `database` 字段**：你们打算自己映射成中文库名，还是直接用我方默认文案？前者的话我把标识符列表钉死在契约里。
5. **§7 delta**：v1 不发答案增量。对话路径（`answering`）技术上可以发——你们那条 `event: delta` 是自己 LLM 的输出，还是想转发我方的？如果是后者，这条要重新评估。
