# Vibe-TLA 使用手册

*用 TLA+ 在你的代码库里找出真实的并发、持久性与顺序性 bug——而无需亲手编写 TLA+。*

> 英文原版：[MANUAL.md](MANUAL.md)。两版内容一一对应；如有出入，以英文版为准。

Vibe-TLA 是一个 Claude Code 技能（skill）。你把它指向一个组件；它会阅读生产源码，写出
**忠实于代码的 TLA+ 规约**（每个被建模的转移都锚定到真实的 `file:line`），用 TLC 做模型
检验，并把每个违例整理成可直接落地修复的 bug 报告——若什么都没坏，则把该性质认证为
**已验证契约（validated contract）**。它为每个仓库维护一个工作区作为长期记忆：今天开始
的猎捕，几周后仍可继续、扩展或复验。

整个技能就是一个循环（*ladder*（阶梯）指把一个组件的验证拆成一串小层级 L0→Ln，每层只
新增一个关注点——详见 §2）：

```
check <component>   → candidate(s)
review [<finding>]  → confirmed  |  retired: refuted      （真阳性闸门）
fix <finding>       → retired: fixed                      （改动 + 验证性复检）
check ...           → 下一轮  （或用 `advance` 爬阶梯的下一级）
```

两条诚实性规则贯穿一切，也是其产出可信的原因：

1. **`check` 从不宣布 bug。** 它只产出*候选（candidate）*。另一个独立的对抗环节
   （`review`）会拿判例清单逐条尝试*证伪*每个候选；活下来的才成为*确认（confirmed）*。
2. **凡是取决于"只有代码负责人（owner）才知道的事实"的发现，一律停在候选状态**——并把
   该事实凝练成一个精确的问题。负责人的回答会把它翻转为确认*或*证伪。无论哪种结果，
   你都得到了一条经过机械化检验的结论。

---

## 0. 命令在哪里输入

vibe-tla 是一个 **Claude Code 技能**：在 Claude Code 会话（CLI 或桌面应用）的输入框里
键入 `/vibe-tla <command>`。安装时，把技能文件夹放到 Claude Code 能发现技能的位置——
二选一：

```bash
# 内嵌（embedded）：随单个仓库走
cp -r vibe-tla  <your-repo>/.claude/skills/vibe-tla
# 或独立（standalone）：所有会话都可用
cp -r vibe-tla  ~/.claude/skills/vibe-tla
```

然后打开会话（内嵌形态下 `cd <your-repo> && claude`），在对话中输入下文的命令即可。

## 1. 初始化——每个仓库一次

**前置条件：** Claude Code（见上）和 Java 运行时（17+）。仅此而已——`init` 会自己找到
或下载 TLC 模型检验器（`tla2tools.jar`），并用一个冒烟规约验证它可用。

```
你：    /vibe-tla init

Claude: 解析得到 <repo-root> = /Users/you/Workspace/pagestore  （内嵌安装）
        $WORKSPACE = <repo-root>/tla
        ✓ TLC 工具链：tla2tools.jar（VSCode TLA+ 扩展）— 冒烟规约通过
        ✓ PROFILE.md — C++ / 分片后台 worker；子系统地图：delta_db、hot_page_mgr、…
        ✓ LESSONS.md 已播种（判例 R1–R5），MEMORY.md / ROADMAP.md 已创建
        最值得先建模的组件：
          1. hot_page_mgr — 多级 LRU、级联淘汰（共享实例、带锁）
          2. …
        运行 `/vibe-tla check <component>` 开始建模。
```

两种安装形态：

- **内嵌（embedded）**——技能位于 `<repo>/.claude/skills/vibe-tla/`；工作区在
  `<repo>/tla/`。建议把 `tla/` 提交进仓库，让记忆随代码走（`init` 会问一次）。
- **独立（standalone）**——技能在你的用户级技能库里；把仓库告诉 init：
  `/vibe-tla init <repo-url-or-path> [--branch B]`。它会克隆到 `~/.vibe-tla/repos/`，
  且 `sync`/`check` 读代码前会先拉取更新。

工作区本身与发现同为产出——`PROFILE.md`（如何忠实地为这个仓库建模）、`MEMORY.md`
（所有已建模内容的台账）、`LESSONS.md`（随每次证伪不断增长的判例）、`ROADMAP.md`
（接下来建模什么），外加每个已建模组件一个文件夹。

**快速上手，按顺序：**

1. `/vibe-tla init`
2. 挑一个组件——从 `init` 打印的"最值得先建模"清单里选，或选你自己最担心的那个。
3. `/vibe-tla check "<组件>" "<你知道的背景>" "<应当永远成立的性质>"`
4. 在对话里读结论；bug 报告（如有）在
   `tla/<component>_models/<ladder>/L0_*/04_counterexamples.md`。
5. 对每个候选：拿到负责人对其唯一待决问题的回答，然后
   `/vibe-tla review <finding> "<回答>"`。

一次 `check` 需要一点耐心：TLC 本身通常几秒跑完，但外围的"读源码 → 写规约 → 甄别"
循环是好几分钟的 agent 工作量。

## 2. 第一次猎捕 —— `check`

```
/vibe-tla check <keywords> [context] [goal]
```

给它三样东西：

| 参数 | 含义 | 示例 |
|---|---|---|
| `<keywords>` | 要建模的组件 / 类 / 目录——不熟悉代码布局时，给一个大致的方向描述也可以 | `"lst_server flush backpressure"` · `"管页面淘汰的那部分"` |
| `[context]` | 你恰好知道的背景——设计事实、疑点、团队答复 | `"响应经就绪队列冲刷；512 MiB 全局输出预算"` |
| `[goal]` | 要验证的开发者预期 | `"每个被接收的请求最终都会被应答"` |

不必知道组件的确切名字。输入很模糊时，`check` 会自己扫描仓库、挑出最匹配的组件、
用一句话说明解读（"把 `<keywords>` 理解为 X，因为……"）、把备选项记入 roadmap 待办，
然后继续跑；只有完全找不到匹配时才会停下来问——也可以加 `--ask` 自己挑目标。

上下文是**提示，不是证据**——建模前，技能会把其中每条断言拿到源码里核实。随后 `check`
无人值守地跑完整个循环：读代码 → 写规约（附 `var ↔ code` 映射表，评审者可以对照源码
阅读规约）→ 运行 TLC（只迭代到*规约本身*能无工具错误地运行为止——性质违例会被保留并
甄别，绝不会被"调参调没"）→ 按判例清单初筛违例 → 写报告 → 更新台账。若会话中途中断，
`/vibe-tla resume` 会从断点继续。

所有产物落在一个可逐文件审计的层级目录里：

```
tla/<component>_models/<ladder>/L{n}_{slug}/
├── 00_input.md            # 提了什么问题 + 收集到的代码事实
├── 01_reasoning.md        # 建模决策、所做抽象及其可靠性论证
├── 02_models/             # 规约 + 全部配置（一个 .cfg 把同一份规约实例化到具体
│                          #   规模——例如 2 级缓存 vs 3 级——从而在多种工况下
│                          #   检验同一份规约）
├── 03_run_log.md          # 精确的 TLC 命令、状态数、耗时
├── 04_counterexamples.md  # 违例轨迹 + 根因 + 甄别  ← 这就是 bug 报告
├── 05_output.md           # 本层证明了什么；忠实度与覆盖率
└── 06_notes.md
```

大组件按**阶梯（ladder）**逐层验证（L0 → Ln），每层只加一个关注点——这样每层都留在
TLC 的预算之内，每个结论都可独立审计。`/vibe-tla advance` 跑下一个计划中的层级；
`/vibe-tla status` 展示台账。

## 3. 一次运行能得出什么结论

| 结论 | 含义 |
|---|---|
| **PASS / 已验证契约（validated contract）** | 在*所检规模下的模型*的完整状态空间上（配置文件精确记录了这些边界），且在代码自身的故障模型下，性质成立。这是货真价实的正确性结论，不是"没找到 bug 的遗憾"。 |
| **候选（candidate）** | 通过了初筛的 TLC 违例；通常钉在一个表述精确的待决前置条件上。下一步跑 `review`。 |
| **确认（confirmed）** | 候选挺过了独立的对抗性证伪（且所依赖的负责人事实已解除）。真阳性。 |
| **结案：证伪 / 设计使然安全（retired: refuted / safe-by-design）** | 对抗环节（或负责人的回答）推翻了它。有记录，且*推翻的理由*会成为 `LESSONS.md` 里的新判例。 |
| **结案：已修复（retired: fixed）** | 修复已应用**并且**经机械化复验——修复后代码的 `*_v2` 规约重跑通过。 |

**如何读一行 TLC 结果**，例如 `AllAnswered violated — 1,391 gen / 457 distinct /
depth 17 — 0.8 s`：*generated* = TLC 生成的状态数，*distinct* = 实际探索的去重状态数
（即搜索规模），*depth* = 最长的步骤序列长度。**安全（safety）不变式**说"坏事永远
不发生"（逐状态检查）；**活性（liveness）性质**（`<>` 读作"最终"）说"好事最终会发生"
——它的反例是一条永远循环、好事却始终不发生的运行（*套索（lasso）*，即永久卡死）。

---

## 三个真实案例

*这些案例都是真实的：来自 bytendb 验证项目（`tla_research/`、`pagestore_models/`），
vibe-tla 正是从该项目的产物与教训中蒸馏而来。下文的规约、TLC 数字、反例轨迹与团队
答复，均逐字引自该项目已提交的产物；`/vibe-tla` 对话则演示今天如何用本技能驱动同一场
猎捕。*

### 案例 1 —— 一个生产卡死 bug 的完整闭环：发现 → 确认 → 修复 → 结案（BUG-006）

**组件：** `pgxn/neon/lst_server.c`——多线程 Unix-socket 服务器，经就绪队列冲刷响应，
受单连接输出预算与 512 MiB **全局**输出预算约束。

#### 发现

```
你：/vibe-tla check "lst_server response flush backpressure" \
      "完成项经就绪队列冲刷；单连接输出预算之外还有 512 MiB 全局输出预算
       (lst_server.c:48)" \
      "每个被接收的请求最终都被应答——不存在永久卡死"
```

技能对代码做忠实转写（零故障注入——若它坏，就是在普通调度下坏），检验活性性质
`AllAnswered == <>(Len(sent) = NFRAMES)`。运行日志里的真实 TLC 结果：

```
hunt_global:      Error: Temporal property AllAnswered was violated.   1,391 gen / 457 distinct / depth 17   0.8 s
perconn_control:  Model checking completed. No error has been found.     249 gen /  86 distinct / depth 14   0.4 s
```

单连接预算的孪生路径是安全的（对照配置通过）；**全局**预算路径会卡死。反例的决定性
一步，逐字引自 `04_counterexamples.md`：

> | 9 | `DrainCompletions` — … `queue_output_frame` sees `over_global_limit` (:3986-3988) →
> refuses, `pause_read(GLOBAL)` (:4001), returns BACKPRESSURE → rc==1 → **re-store completion
> (:4157), `pause_read(OUTPUT)` (:4158), break (:4159)**. Nothing sent; **no ready-queue push;
> `outQ` still 0 ⇒ EPOLLOUT not armed** |
>
> In the terminal state: `comp={0,1}` (two responses fully computed and stored), `ready=F`,
> `outQ=0`, `deferred=T`, `pause={PIPE}`, `sent=<<>>` — three requests accepted, zero
> answered, **forever**.

（终态含义：两个响应已经算完并存好，但就绪标志为假、输出队列为空——三个请求被接收，
应答数为零，**永远如此**。）

根因，直接来自规约所引用的源码（`lst_server.c:4154-4166`）：

```c
rc = lst_conn_send_one_response(conn, target_seq, resp);
if (rc == 1)
{
    (void) lst_conn_store_completion(conn, target_seq, resp);
    lst_conn_pause_read(conn, LST_PAUSE_OUTPUT_BUDGET);
    break;                       /* <-- no push_once, no signal, no epoll change */
}
```

被全局预算拒绝的完成项被原样存回，**却没有留下任何唤醒边**——而且这个卡死会活过引发
它的过载期。`check` 将其分类为**候选**，并附一个待决前置条件：*生产环境中
`lst_global_out_bytes` 能否超过 512 MiB？*

#### 确认

```
你：/vibe-tla review L1_backpressure "负责人：会——全局排队超过 512 MiB 在生产可达；
     唤醒边审计已逐条核对，不存在其他恢复路径"

Claude: 已在提交的规约上复现该轨迹（457 个去重状态——真实存在）。
        对抗性重跑 R1–R5 清单：存在行为见证（已算出却永不送达的响应）、唤醒边已
        穷举、前置条件已解除。
        CONFIRMED —— 真阳性。建议的修复形态（约 5 行）：在 rc==1 路径里推入就绪
        队列并 signal eventfd。  → /vibe-tla fix L1_backpressure
```

#### 修复与结案（本例：团队自行修复，经 `sync` 结案）

这次是团队自己发布了修复（MR !357：恢复边
`lst_conn_schedule_ready_completion_if_unblocked`、512/384 MiB 迟滞、连接关闭时的预算
释放——与建议的形态一致）。修复落地后，`sync` 察觉模型已过期，随后的复检**以机械方式**
结案，而不是凭感觉：

```
你：/vibe-tla sync lst_server

Claude: 3 处锚点发生实质漂移：新增 lst_server.c:2664-2691
        （schedule_ready_completion_if_unblocked，在 :2951 被调用）、迟滞 :48-49、
        关闭时释放 :1879 → 正在为修复后的代码重新建模……

        修复后模型（N=2 连接，使用真实的共享全局计数器）：
          PASS — AllAnswered HOLDS。3,383 generated / 702 distinct / depth 17。0.8 s。
          全部安全不变式成立，含 GlobalAccountingExact（globalOut = Σ outQ[c]）。
        去守卫（removed-guard）演示证明修复的两半各自都不可或缺：
          RECOVERY_EDGE=FALSE  → 卡死自行重现（AllAnswered violated，736 distinct）
          RELEASE_ON_CLOSE=FALSE → 计数器泄漏；幸存连接仍会卡死（1,132 distinct）
        模型升级为 *_v2；台账已更新 —— BUG-006 已修复，机械化验证通过。
```

引自结案报告：*"The single call at `lst_server.c:2951`
(`schedule_ready_completion_if_unblocked`) is the entire difference."*（`:2951` 这一处
调用就是全部差异。）这正是本技能围绕的完整闭环：**模型发现活性 bug → 修复 → 机械化
结案**——去守卫演示则作为回归绊线（tripwire）永久留在工作区里。

若团队没有发布修复，`/vibe-tla fix L1_backpressure` 可以从你这边闭环：把建议的补丁
应用到你的工作树、展示 diff（未经询问绝不 commit/push），并自行完成同样的 `*_v2`
复检。

### 案例 2 —— 今日被掩盖，设计形态下真实存在（BUG-010）

**组件：** PageStore 的 `MultiLevelLRU` 热页缓存（`hot_page_mgr/multi_level_lru.cc`）。
这个案例说明了为什么 `review` 必须读*设计文档*，而不只是读代码。

```
你：/vibe-tla check "hot_page_mgr multi-level LRU cascading eviction" \
      "服务端热页缓存；当前部署为 2 级" \
      "任一页永远不会同时驻留在两个 LRU 层级；计数器保持一致"
```

真实结果：在**已部署**的配置上性质成立；宽一级，就不成立了。

```
production_2tier.cfg   (2 levels)  No error — all invariants hold      5,725 gen /  63 distinct / depth 8
three_tier_demo.cfg    (3 levels)  UniqueLocation VIOLATED at depth 4  3,594 gen /  35 distinct
```

缺陷是一个*读旧值再行动（stale-read-then-act）*的形态（`04_counterexamples.md`）：

```c
auto old_level = get_page_heat_level_unlocked(seg_id, page_no);    // :231  captured ONCE
bool ready = cascading_demote(target_level);                       // :244  may move (seg,page)!
levels_[old_level].remove_page(seg_id, page_no);                   // :254  stale level → no-op
levels_[target_level].insert_page(seg_id, page_no, current_clock); // :258  second copy
```

级联淘汰可能把*正在被标记的那个页*降了级；随后对旧层的移除成了空操作，最后的插入让
这个页同时出现在**两个层级**——破坏 `is_page_hot`、`get_page_heat_level`、
`unmark_page_hot`，并让 `size()` 重复计数。

**陷阱——以及技能如今固化下来的教训。** 早期甄别曾用一个"树内的、封闭的"边界*证伪*
了这个发现：生产构造器最多只建 ≤ 2 层（`page_engine.cc:1851-1858`），而 2 层下该轨迹
不可达。随后负责人拿出了设计文档：

```
你：/vibe-tla review L0_cache_integrity "负责人设计文档：DBEngine 定义了五个缓存
     热度层（page_cache_level_t cache_level_1..5）；HotPageMgr 按设计每个热度层
     跑一个 LRU 层——层数正在从 2 → 5 演进"

Claude: "≤ 2 层"这个边界是**开放的**，不是封闭的——设计正在移动它（判例 R4.4）。
        改在**设计目标工况**下复检：five_level_stable.cfg —— 5 层，每个页钉死在
        固定热度（完全不发生热度变化）……
        UniqueLocation VIOLATED at depth 4（140 distinct；≈28 s，-workers auto）。
        普通的"降级后再标记"流量就会让同一页重复驻留。候选**维持不倒（STANDS）**
        ——一个待决前置条件：多层（≥3）的 HotPageMgr 是否就是目标部署形态？
```

五层反例就是缓存最平常的日常——不需要任何刁钻的边角情形：

```
Access(3)  heat 2  →   L0:{}    L1:{}    L2:{3}        3 at its heat
Access(8)  heat 2  →   L0:{}    L1:{3}   L2:{8}        3 demoted below its heat
Access(3)  heat 2  →   L0:{3}◀  L1:{8}   L2:{3}◀   ← 3 duplicated (L0 and L2)
```

团队确认多层设计就是目标 ⇒ **CONFIRMED**（2026-06-30）——一次*左移（shift-left）*
捕获：**在今天的 2 级二进制里被掩盖，在设计的 5 级缓存下真实存在**，在上线之前就被
抓住。建议的修复只有一行（在 `cascading_demote` 之后重读 `old_level`）；截至本文撰写
时修复尚未落地，而计划中的结案同样是机械化的——在打上补丁的流程上重跑
`five_level_stable.cfg`，看 `UniqueLocation` 成立。这次险些误判成为了永久判例
（`LESSONS.md`）：*R4.4——"封闭"意味着设计也没在移动这个边界；R4.5——要建模设计
目标工况，而不只是当前部署形态。* 此后每个仓库的每次 `review` 都会跑这份清单。

### 案例 3 —— 证伪本身就是赢（BUG-007/008/009）

并非每个违例都是 bug——而 vibe-tla 的设计让被证伪的候选同样有回报：它把 PASS 升格为
**已验证契约**，并留下绊线。

**组件：** PG-on-dbstore 的页身份编码器 `GetSpaceNo`
（`pgxn/neon/ondbstore/ondbstore_key.h:51`）——把 `(db, rel, fork)` 打包进 64 位，
**丢弃了 `spcNode`，并把 `dbNode` 截断到 24 位**。

```
你：/vibe-tla check "GetSpaceNo ondbstore_key segment key encoding" \
      "" "不同的 PG 页身份 (spc,db,rel,fork) 在编码后的键上永不碰撞"
```

TLC 在此充当穷举的位级检查器——每个有序键对都是一个初始状态：

```
canonical.cfg          KeyInjective + 4 more PASS over 20,736 pairs        0.7 s
tablespace_alias.cfg   KeyInjective VIOLATED  (spcNode dropped)            0.3 s
dbnode_alias.cfg       KeyInjective VIOLATED  (dbNode & 0xFFFFFF aliases)  0.3 s
```

模型**并不**比代码更宽松——编码器确实在丢弃、确实在截断。于是按判例 R1.4，这是两个
**候选**（BUG-007/008，"若可达则为高危"），各钉在一个精确的负责人问题上：*用户表空间
是否被禁止？`dbNode < 2²⁴` 是否有保证？* BUG-007 的见证（witness）只有一行：

```
k1 = [spc |-> 0, db |-> 0, rel |-> 0, fork |-> 0]
k2 = [spc |-> 1, db |-> 0, rel |-> 0, fork |-> 0]     Enc(k1) = Enc(k2), yet k1 ≠ k2
```

团队用一句话同时回答了两个问题：

```
你：/vibe-tla review segment_mapping "团队: 这个是设计背景，就是不需要 spcNode，
     且 dbNode 只要 24bit"

Claude: 两类被排除的输入都**按设计不可达** →
        BUG-007、BUG-008：结案 —— REFUTED（safe by design，设计使然安全）。
        canonical 配置的 PASS 就此升格：该编码如今是团队确认的生产域之上的
        **已验证契约（VALIDATED CONTRACT）**——它所依赖的两个域边界已是确认的
        事实，不再是待决假设。
        违例配置**保留**为边界演示——绊线，精确展示一旦设计允许用户表空间或
        dbNode ≥ 2²⁴ 时会坏掉什么。
        引用判例：R4.1–R4.3（"答案就是发现"，裁向证伪同样成立）。
```

R4 系列规则正是从这个案例蒸馏出来的——如今它们随技能的种子 `LESSONS.md` 一起发布，
每个新仓库开局即有。

当边界是**部署**事实而非设计事实时，同一套纪律照样适用：BUG-009（同一天；某流控 cap
下限当且仅当 `min_cap > mem_hard_cap` 时才可能击穿内存预算）被一句话证伪——生产 VM 规格把
`mem_hard_cap` 钉死在 1 GiB，击穿不可达——留下一条加固备注（在代码里断言该边界）作为
纵深防御。

**记分逻辑：** 这里 0 个 bug——却照样收获三项有机械化背书的成果：一份已验证的编码
契约、两根回归绊线、新增判例。对称的诚实正是特性所在：负责人的回答把候选翻向确认*或*
证伪；你的先验不算数。

---

## 4. 日常运维

**`/vibe-tla status [keywords]`**——台账一览：已关闭层级及其结论、待决候选（以及各自
在等哪条事实）、中断待续的工作、漂移警告、下一个待办项。每个阶梯还维护一份
`TODO.md`——"哪些是待办、下一条命令跑什么"的单点摘要。

**`/vibe-tla sync <keywords>`**——"代码是不是从模型脚下漂走了？"它会重读模型记录的
每个 `file:line` 锚点。无实质漂移 → 报告*"模型仍然忠实——无需重跑"*，并列出核对过的
锚点作为证据。有实质漂移 → 告诉你哪个锚点变了、旧貌与新貌，并把模型升级为 `*_v2`
（案例 1 的结案正是这样开始的）。`references/ci-integration.md` 介绍了如何把它接入
CI：PR 一旦触碰已建模的代码，自动标记模型漂移。

**`/vibe-tla resume [keywords]`** vs **`/vibe-tla advance [ladder]`**——`resume` 完成
一次*被中断*的运行（从 `MEMORY.md` 里的 `## STAGED` 注记继续）；`advance` 跑一个干净
收尾的阶梯的下一个*计划中*层级。两者绝不混为一谈。

**`/vibe-tla coverage [keywords]`**——挑剔的评审者要的两个数字：模型覆盖了多少*代码*
（已建模的转移 vs 标为 `UNCLEAR` 的），以及*模型本身*是否被充分执行到（TLC 动作覆盖率
——零覆盖的动作是死规约：一个从未成立的守卫，往往是一个真实的建模 bug）。

**`/vibe-tla effort <high|low|medium>`**——控制 `check` 探索的穷尽程度（模型规模、
配置数量、故障变体、TLC 时间预算）。可设为工作区默认值，也可单次覆盖：
`check <keywords> --effort high`。承重子系统用 `high`。

## 5. 命令速查

| 命令 | 作用 |
|---|---|
| `init [repo-url]` | 一次性初始化：工作区、TLC 工具链、架构画像、记忆文件 |
| `check <keywords> [context] [goal] [--ask]` | 完整的发现循环：读代码 → 写规约 → TLC → 甄别 → 报告。keywords 可以很模糊——它会自己定位目标（加 `--ask` 则由你来挑）。只产出**候选** |
| `review [finding]` | 对抗性真阳性闸门 → confirmed / retired: refuted。附上 `"<负责人回答>"` 可解除前置条件 |
| `fix <finding>` | 把最小改动应用到你的工作树（展示 diff；未经询问绝不 commit/push），**并**给出证明：`*_v2` 规约重跑通过 → retired: fixed |
| `sync <keywords>` | 用当前代码重新校准模型锚点；有实质漂移则修订 |
| `resume [keywords]` | 从暂存注记继续一次被中断的 `check` |
| `advance [ladder] [--to Ln \| --count N]` | 运行该阶梯的下一个（批）计划层级 |
| `status [keywords]` | 只读台账 + 下一步建议 |
| `coverage [keywords]` | 忠实度 + TLC 动作覆盖率报告 |
| `effort <high\|low\|medium>` | 默认探索深度（单次覆盖：`--effort`） |

## 6. 用好它的五个习惯

1. **给 `check` 一个真正的目标。**"每个被接收的请求最终都被应答"胜过"帮我找找 bug"
   ——TLC 检验的就是这条性质。把开发者预期说出来。
2. **提供上下文，但预期它会被核实。** 设计事实、疑点、团队答复都有用；技能把它们当
   提示，并从源码重新推导。核实不了的会标为 `UNCLEAR`，只有负责人才能确认的事实会让
   发现停在候选。
3. **把候选附带的负责人问题当成交付物。** 它是一个带具体见证的精确问题（案例 3 的
   问题一句话就答完了）。拿去问负责人，然后
   `review <finding> "<回答>"`——无论哪种结果都是成果。
4. **有设计文档就拿出来。** 案例 2 的 bug 在已部署配置下不可见，正是因为建模了设计
   目标工况才得以确认。代码今天的行为不等于全部的定义域。
5. **保留工作区。** 把 `tla/` 提交进仓库。规约是回归绊线，`MEMORY.md` 是审计轨迹，
   `LESSONS.md` 让每次证伪成为永久财富，而 `sync` 让这一切随代码演进保持诚实。

*深入阅读：`references/commands.md`（每个命令的精确流程）、`methodology.md`（阶梯
方法、转写与故障注入两种模式、完工定义）、`lessons.md`（完整的 R1–R5 判例）、
`authoring.md`、`coverage.md`、`tlc-setup.md`、`ci-integration.md`。*
