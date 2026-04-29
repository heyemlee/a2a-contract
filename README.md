# A2A 接口契约（跨仓库共享）

这里放 `ai-sql-agent`（A2A 服务端）与 `ai-helpdesk`（A2A 客户端）之间的接口契约。

放在两个仓库之外，是因为它**同时**约束两边：留在任何一侧都会变成
"一方的文档"，而契约变更必须是双边事件。

## 内容

| 路径 | 说明 |
| --- | --- |
| [`a2a-streaming-contract.md`](a2a-streaming-contract.md) | `message/stream` 流式契约。**唯一权威副本** |
| [`CONSUMER-TESTS.md`](CONSUMER-TESTS.md) | 两侧 CI 各自必须跑的用例（A–F 六组，两条 transport 共用一组） |
| [`schema/`](schema/) | JSON Schema：artifact data part、progress 事件信封、`stage` 与 `database` 枚举 |
| [`fixtures/`](fixtures/) | 跨仓库 golden fixtures：正例 + schema 反例 + 信任反例。清单在 `fixtures/index.json` |
| [`tools/check_contract.py`](tools/check_contract.py) | 本仓库自检：schema 自校验 + fixtures 校验 + 文档内链接检查 |

## 规矩

- 契约变更 = **双边事件**。任何一侧不得单方面修改后直接实现。
- 两个仓库都不再各存一份副本，只引用这里，避免副本漂移。
- 文档顶部的**状态行**（草案 / vX.Y）就是当前生效版本，也是判别权威副本的第一道判据。
- **状态行里关于"做没做"的每一句话都要附可复核证据**：文件路径:行号 / 测试文件名 /
  可重跑的命令。写不出证据的写成"待核实"，不要写成事实。这个仓库为此翻过两次车
  （v1.2、v1.4），第三次的教训见契约附录 B 的自检表。

## 两侧怎么引用（**带 tag 或 commit，不要跟 main**）

在代码注释或文档里引用时，写清楚**引的是哪一版**：

```python
# 契约见 a2a-contract 仓库的 a2a-streaming-contract.md（v1.5，tag v1.5 / commit <sha>）
```

**只写版本号不够，只写 `main` 更不行。** 版本号会被下一版顶掉，`main` 会动；
读注释的人需要能取到**当时那一份**。

CI 里取 fixtures / schema 时钉在 tag 上：

```bash
git clone --depth 1 --branch v1.5 https://github.com/heyemlee/a2a-contract.git .contract
```

或加成 submodule（submodule 天然钉在 commit 上，最省心）：

```bash
git submodule add https://github.com/heyemlee/a2a-contract.git .contract
```

**不要把 `schema/` 或 `fixtures/` 拷进实现仓库。** 拷贝就是副本，副本会漂——
这正是这份契约当初被挪出来单独放的原因。

### 升版本的时候

改契约 = 两侧都要跟着改引用。顺序是：

1. 本仓库改文档 → `python3 tools/check_contract.py` 全绿 → 合入 `main`；
2. 打 tag（`vX.Y`），tag 消息里写清这一版改了什么、哪些条款还是缺口；
3. 两侧各自把引用里的版本号和 commit 换掉，并把新增/变更的用例接进自己的 CI。

第 3 步没做完之前，**不要在状态行里声称"两侧已实现"**——那正是 v1.2 和 v1.4
各自栽过的地方。

## 自检

```bash
pip install jsonschema referencing
python3 tools/check_contract.py
```

CI 在 push / PR / 打 tag 时自动跑同一条命令，见
[`.github/workflows/contract.yml`](.github/workflows/contract.yml)。

## 版本

| tag | 状态行 |
| --- | --- |
| `v1.5` | 链路已通；七条条款未兑现，逐条在正文标了 ⚠️ 缺口 |

> v1.0–v1.4 没有 tag（这个仓库到 v1.5 之前是零 tag，而附录 B 却要求引用时带 commit——
> 那条规矩当时没有可执行的落法）。历史版本请按附录 A 的变更记录找对应 commit。
