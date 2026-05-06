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
| [`tools/check_contract.py`](tools/check_contract.py) | 本仓库自检：schema 自校验 + fixtures 校验 + 文档内链接检查 + 版本号一致性。**四段判据只有这一个地方知道**，CI 只负责调它 |

## 目录结构：**这几个路径是被下游硬编码的，不要重排**

这个仓库看起来像"文档太多、该整理一下"，但它的布局是**接口的一部分**。
两个实现仓库不是读这份 README，是直接按路径读文件：

| 下游位置 | 它按死路径读的东西 |
| --- | --- |
| `ai-sql-agent/tests/test_contract_fixtures.py` | `schema/*.schema.json`、`fixtures/index.json`、`schema/database-id.schema.json`、`schema/stage.schema.json` |
| `ai-helpdesk/backend/tests/test_contract_fixtures.py` | 同上；找不到仓库时退到**同级目录** `../a2a-contract` |
| 两侧 `.github/workflows/ci.yml` | `clone --branch <tag>` 之后读 `.contract/fixtures/index.json` |
| 两侧代码注释 | "见 a2a-contract 仓库 `a2a-streaming-contract.md`" |

所以：

- **`schema/`、`fixtures/`、`tools/`、`a2a-streaming-contract.md` 的位置不能动。**
  把它们收进 `src/` 或 `docs/` 会让两侧在**下一次升 pin 时**整片变红——
  而且红的地方在别人的仓库里，不在这里。
- 已经打出去的 tag 里是旧布局。重排之后，钉旧 tag 的引用与钉新 tag 的引用
  **不再同构**，附录 B 那句"钉住的引用必须一直取得到当时那一份"就废了。
- 真要重排，那是一次**三仓库同步变更**，按 §6 的双边流程走，不是一次整理。

**这个仓库为"引用取不到 / 副本漂了"翻过四次车。重排目录是这个仓库能做的
风险最高的操作，因为它一次性把所有引用都动了。**

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
# 契约见 a2a-contract 仓库的 a2a-streaming-contract.md（v1.11，tag v1.11 / commit <sha>）
```

**只写版本号不够，只写 `main` 更不行。** 版本号会被下一版顶掉，`main` 会动；
读注释的人需要能取到**当时那一份**。

CI 里取 fixtures / schema 时钉在 tag 上：

```bash
git clone --depth 1 --branch v1.11 https://github.com/heyemlee/a2a-contract.git .contract
```

或加成 submodule（submodule 天然钉在 commit 上，最省心）：

```bash
git submodule add https://github.com/heyemlee/a2a-contract.git .contract
```

**不要把 `schema/` 或 `fixtures/` 拷进实现仓库。** 拷贝就是副本，副本会漂——
这正是这份契约当初被挪出来单独放的原因。

### 升版本的时候

改契约 = 两侧都要跟着改引用。顺序是：

1. 本仓库改文档。**版本号要一次改齐五处**，`python3 tools/check_contract.py version`
   会逐处核对，改漏哪一处它会点名：

   | # | 在哪 |
   | --- | --- |
   | 1 | `a2a-streaming-contract.md` 的状态行 —— **这是唯一的真值来源** |
   | 2 | 契约附录 A 变更记录的新增行 |
   | 3 | `README.md` 版本表的新增行（本文件下方） |
   | 4 | `fixtures/index.json` 的 `contract_version` —— **下游真正读的是这个** |
   | 5 | 所有 `--branch vX.Y` 示例，以及 `CONSUMER-TESTS.md` 抬头的「配套：…」 |

2. `python3 tools/check_contract.py` 全绿 → 合入 `main`；
3. **打 tag（`vX.Y`）——这必须是这一版的最后一个动作。**
   tag 消息里写清这一版改了什么、哪些条款还是缺口；
4. 两侧各自把引用里的版本号和 commit 换掉，并把新增/变更的用例接进自己的 CI。

第 4 步没做完之前，**不要在状态行里声称"两侧已实现"**——那正是 v1.2 和 v1.4
各自栽过的地方。

> **第 3 步为什么要强调"最后一个动作"。** v1.10 就是打完 tag 之后又补了三笔提交
> （`70fb56d`、`77cadca`、`75eafe8`），于是 tag `v1.10` 里的 `contract_version`
> 永远停在 `v1.9`，下游钉它会红一条版本断言。而已经推送的 tag **不能移动**
> （附录 B：钉住的引用必须一直取得到当时那一份），只能再补一个自洽的 tag ——
> 那就是 v1.11 存在的全部理由，它的契约面与 v1.10 **逐字节相同**。
>
> **补正想好了再打 tag；已经打了就别再往那一版上加东西。**
> 真的漏了，补新 tag，不要动旧的。

## 自检

```bash
pip install jsonschema referencing
python3 tools/check_contract.py
```

四段，可以单独跑其中一段：

| 段 | 跑什么 | 防的是 |
| --- | --- | --- |
| `schema` | schema 自己合法；契约点名的枚举真在 schema 里 | 正文表格写了、schema 没跟上 |
| `fixtures` | 清单与文件对得上；**反例真的被拒** | 用例分叉；一条不报错的反例 |
| `links` | §小节引用与文件路径都指向真实存在的东西 | 引用一个不存在的小节 / 文件 |
| `version` | 每一处"当前钉哪一版"都等于状态行 | 版本号漂移（见下） |

```bash
python3 tools/check_contract.py version
```

**`version` 段是 v1.11 扩出来的，起因值得记住。** 它原先只比一处
（`fixtures/index.json` 的 `contract_version`），而真正漂掉的是它没看的地方：
`CONSUMER-TESTS.md` 抬头那句「配套：…（v1.5）」**活过了 v1.6–v1.10 五个版本**，
调用方早在 v1.6 就把它写进交回契约的反馈清单，**写了也没人改**。
原因不是谁不认真——**没有任何机器在看那一行**。现在它按形态收全五处：
两张版本表的最新行、`contract_version`、`--branch` 示例、文档抬头的「配套：」。

> 为了不给下一个人挖坑，`version` 段**只看会被复制粘贴去执行的行**：
> Markdown 里 ``` 围栏内的行、YAML 里的非注释行。附录 A 的变更记录可以放心
> 写"把 `--branch v1.11` 改成 `--branch v1.12`"，那是叙述，不会误报。

CI 在 push / PR / 打 tag 时跑的就是不带参数的那一条，见
[`.github/workflows/contract.yml`](.github/workflows/contract.yml)。
**CI 里不再写第二份断言**——判据分散在两个地方，就等于没有一个地方知道判据的全集，
v1.10 那次漂移漏掉的正是当时写在 workflow 里那段 bash 没覆盖的两处。

## 版本

| tag | 状态行 |
| --- | --- |
| `v1.11` | **契约面与 v1.10 逐字节相同**，只补一个自洽的版本号：tag `v1.10` 里 `contract_version` 停在 `v1.9`（三笔补正落在打 tag 之后），下游钉它会红一条版本断言。`v1.10` 已推送不能移动，所以补 tag 不移 tag。两侧 pin 由 `v1.8` 直接改到这里 |
| `v1.10` | 七条缺口全部关闭；**判据是降级的**——原计划「两侧 CI 在 GitHub 上绿一次」一次都没发生（账号级 `Actions has been disabled for this user`），实际判据是「提交可推送复核 + 本机按 CI 入口复现全绿」。**⚠️ 这个 tag 的 `contract_version` 停在 `v1.9`，不要钉它，钉 `v1.11`** |
| `v1.9` | `dp-trust-01` 的进度标记挂错了对象——fixture 断判据、活载荷断进度，两件事拆开；新增 `dp-trust-07` |
| `v1.8` | 把 `/query` 纳入契约（它是今天的默认路径，此前一直在保护范围外）；§4.6.5 币种改为按来源三分 |
| `v1.7` | 两侧各实现一轮，暴露出契约自己的三个错——先改错，再记进度 |
| `v1.6` | 两个双边决定落地：send 补第三档、`database` 由钉死枚举改为形状 + 清单 |
| `v1.5` | 链路已通；七条条款未兑现，逐条在正文标了 ⚠️ 缺口 |

> v1.0–v1.4 没有 tag（这个仓库到 v1.5 之前是零 tag，而附录 B 却要求引用时带 commit——
> 那条规矩当时没有可执行的落法）。历史版本请按附录 A 的变更记录找对应 commit。
