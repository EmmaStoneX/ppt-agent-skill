# 智能体会话日志分析方法论（详细实操版）

> 基于 PPT Agent 两次测试日志的分析实践总结
> 适用于：类 OpenClaw / Claude Code / 任何 LLM Agent 框架的 JSONL 格式会话日志
>
> 配套分析脚本位于 `log_analysis/` 目录，所有脚本零外部依赖（仅 Python 标准库）
> 作者：@10111841


---

## 前置知识：JSONL 日志格式

智能体框架通常以 JSONL（每行一个 JSON 对象）格式记录会话日志。
不同框架的字段结构有差异，本工具集兼容两种主流格式：

### 新格式（OpenClaw / 类 OpenAI 兼容框架）

```jsonc
// 第一行: 会话元信息
{"type": "session", "id": "...", "version": 3, "cwd": "/path/to/project", ...}

// 模型切换
{"type": "model_change", "provider": "zte", "modelId": "step-3.5-flash", ...}

// 消息行（核心）
{"type": "message", "timestamp": "2026-03-26T02:22:41.971Z",
 "message": {
   "role": "user|assistant|toolResult",
   "content": [{"type": "text", "text": "..."}, {"type": "toolCall", "name": "exec", "arguments": {...}}],
   "usage": {"input": 13856, "output": 1234, "cacheRead": 0, "totalTokens": 15090},
   "stopReason": "toolUse|stop|error",
   "errorMessage": "terminated"  // 仅 error 时有
 }}

// 上下文压缩
{"type": "compaction", "timestamp": "...", "tokensBefore": 111937, ...}
```

### 旧格式（Claude CLI / Anthropic SDK）

```jsonc
// 消息行
{"type": "assistant", "timestamp": "2026-03-23T10:31:01.201Z",
 "message": {
   "model": "claude-opus-4-6", "role": "assistant",
   "content": [{"type": "thinking", ...}, {"type": "text", "text": "..."}, {"type": "tool_use", "name": "Bash", "input": {...}}],
   "stop_reason": "tool_use|end_turn|stop_sequence",
   "usage": {"input_tokens": 50000, "output_tokens": 3000, "cache_read_input_tokens": 10000, ...}
 }}

// 系统事件
{"type": "system", "subtype": "api_error", "error": {"status": 529}, "retryAttempt": 1, "maxRetries": 3, "retryInMs": 15000}
{"type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto", "preTokens": 200000}}
{"type": "system", "subtype": "turn_duration", "durationMs": 45000}
```

### 关键字段差异速查

| 特征 | 新格式 | 旧格式 |
|------|--------|--------|
| 消息类型 | `type: "message"` + `role` | `type: "assistant"/"user"` |
| 工具调用 | `type: "toolCall"`, `arguments` | `type: "tool_use"`, `input` |
| 停止原因 | `stopReason`: toolUse/stop/error | `stop_reason`: tool_use/end_turn |
| Token 字段 | `input`/`output`/`cacheRead` | `input_tokens`/`output_tokens`/`cache_*` |
| 错误标记 | `stopReason: "error"` + `errorMessage` | `isApiErrorMessage` + `system.subtype: "api_error"` |
| 压缩事件 | `type: "compaction"` | `system.subtype: "compact_boundary"` |

---

## 快速开始

```bash
# 1. 一键生成汇总报告（先跑这个，了解全貌）
python3 log_analysis/10_summary.py your_log.jsonl

# 2. 发现问题后，用对应维度脚本深入分析
python3 log_analysis/02_errors.py your_log.jsonl      # 有 error? 看这个
python3 log_analysis/03_context_growth.py your_log.jsonl  # 上下文爆了? 看这个
python3 log_analysis/06_quality_check.py your_log.jsonl   # 输出质量差? 看这个

# 3. 修复后，对比两次日志的改进效果
python3 log_analysis/04_compare.py old_log.jsonl new_log.jsonl
```

---

## 10 维度详细说明

### 维度 1: 会话时间线

**脚本**: `01_timeline.py`
**目标**: 梳理完整执行流程，建立时间基准。

```bash
python3 log_analysis/01_timeline.py logfile.jsonl
```

**输出示例**:
```
 行号    时间  角色            摘要
------------------------------------------------------------
    0  10:22  SESSION         id=f365c14a15 cwd=/home/user/project
    1  10:22  MODEL           zte / step-3.5-flash
    4  10:22  USER            请帮我做一个关于AI安全的PPT
    5  10:22  ASSISTANT       [tool:read] (in=13856 out=1234)
    7  10:23  TOOLRESULT      [tool_result]
   ...
```

**核心逻辑**:
- 自动检测日志格式（新/旧），统一提取时间戳、角色、内容摘要
- 工具调用显示为 `[tool:工具名]`，文本内容截取前 50 字符
- 附加 usage 信息和非正常的 stopReason

**看什么**:
- 相邻消息之间的时间间隔（长间隔 = 可能卡住或在执行长时间操作）
- 各 Step 的时间范围和占比
- user 消息出现的时机（是主动操作还是被迫"继续"）

---

### 维度 2: 异常终止事件

**脚本**: `02_errors.py`
**目标**: 找出所有非正常结束的 API 调用，区分故障来源。

```bash
python3 log_analysis/02_errors.py logfile.jsonl
```

**输出示例**:
```
共发现 5 个异常事件:

 行号                 时间  类型                输入tok    输出tok  详情
----------------------------------------------
   41  2026-03-26 02:30:33  STOP:error                0         0  terminated
   81  2026-03-26 02:41:15  STOP:error                0         0  terminated
  113  2026-03-26 02:59:22  STOP:error                0         0  terminated

--- 异常类型汇总 ---
  STOP:error: 5
```

**关键判断逻辑**:

| stopReason | usage 全为 0 | 含义 | 行动 |
|-----------|-------------|------|------|
| error | ✅ | API 连接层失败，请求没到达模型 | 查框架超时配置/网络 |
| error | 有值 | 模型推理过程中出错 | 查上下文大小/Prompt |
| length | output=N | 命中 max_tokens 硬上限 | 增大 max_tokens 或分批输出 |

**实战案例**: 第一次测试 4 次 length（output=8192）→ 诊断为 max_tokens 太小，
修复后第二次测试 0 次 length，改为 5 次 error（usage=0）→ 是 API 连接问题。

---

### 维度 3: 上下文增长曲线

**脚本**: `03_context_growth.py`
**目标**: 追踪 input_tokens 增长趋势，找出膨胀点。

```bash
python3 log_analysis/03_context_growth.py logfile.jsonl
```

**输出示例**:
```
  #   行号    时间   输入tok   输出tok      增量  工具/上下文                标注
-----------------------------------------------------------------
  0      5  10:22     13,856    1,234   +13,856  read
  1      9  10:23     24,506    2,100  +10,650  read                    <-- 显著增长
  ...
 25    109  10:58     74,905    3,200   +1,856  exec
 30    148  11:08    111,937    2,800   +3,164  write                   <-- 峰值!
 31    150  11:09          0        0  -111,937  COMPACTION              <-- 压缩前 111937 tokens

--- 统计 ---
  最大 input tokens: 111,937
  Compaction 次数:   1
```

**核心逻辑**:
- 提取每次 assistant 回复的 `input_tokens`
- 计算与上一次的增量 (delta)
- 自动标注异常增长（>10K "显著增长"，>20K "大幅增长"）
- 识别 compaction 事件（上下文压缩）

**看什么**:
- **突然跳涨**（如 +16K）：检查对应行号，看是哪个 read/toolResult 注入了大量数据
- **持续线性增长**：正常，但如果逼近模型上限就要警惕
- **compaction 触发点**：说明框架认为上下文太大了

---

### 维度 4: 修复效果对比

**脚本**: `04_compare.py`
**目标**: 量化对比修复前后的关键指标。

```bash
# 对比两份日志
python3 log_analysis/04_compare.py old_log.jsonl new_log.jsonl

# 也可以只看单个日志的指标
python3 log_analysis/04_compare.py single_log.jsonl
```

**输出示例**:
```
==============================================================
修复效果对比报告
==============================================================
  指标                    基线(文件1)            修复后(文件2)          变化
  --------------------    --------------------   --------------------   ---------------
  总行数                  70                     162                    +131.4% ^
  API 调用次数            30                     77                     +156.7% ^
  最大 input tokens       58,020                 111,937                +92.9% ^
  错误数                  6                      5                      -16.7% v
  会话时长(分)            35.3                   50.5                   +43.1% ^
```

**核心逻辑**:
- 对两份日志分别提取：行数、API 调用数、token 消耗、错误数、时长、工具分布
- 计算百分比变化，`v` 表示改善（数值下降更好），`^` 表示恶化
- 输出 stop_reason 分布对比和工具调用分布对比

---

### 维度 5: 工具调用统计

**脚本**: `05_tool_stats.py`
**目标**: 了解模型调用了哪些工具、频率和内容量。

```bash
python3 log_analysis/05_tool_stats.py logfile.jsonl
```

**输出示例**:
```
工具名                    调用次数    输入总量      输出总量      平均输出      最大输出    错误数
-----------------------------------------------------------------------------------------------
exec                          18       12,340      245,000      13,611       85,000       2
read                          15        3,200      180,000      12,000       30,017       0
write                         12      125,000            0           0            0       0

--- 最大输出 TOP 20 ---
 行号  工具名                输入大小    输出大小  错误?  参数预览
-------------------------------
   47  read                       45      30,017         file_path=references/prompts.md
```

**核心逻辑**:
- 提取所有 toolCall/tool_use 块，记录工具名和参数大小
- 匹配对应的 toolResult，计算输出大小
- 汇总每种工具的调用次数、总输入/输出、最大输出
- 列出输出最大的 TOP 20 调用（往往是上下文膨胀的元凶）

**看什么**:
- **最大输出 TOP 20**：输出最大的 read 操作就是上下文膨胀的直接原因
- **错误数 > 0 的工具**：说明该工具执行不稳定
- **调用次数异常多的工具**：可能有重复调用浪费

---

### 维度 6: 输出质量检查

**脚本**: `06_quality_check.py`
**目标**: 检查生成内容是否符合设计规范。

```bash
python3 log_analysis/06_quality_check.py logfile.jsonl
```

**输出示例**:
```
共发现 28 个质量问题

--- 问题类型汇总 ---Let's build
Plan, search, or build anything

Vibe
Chat first, then build. Explore ideas and iterate as you discover needs.
Spec
Plan first, then build. Create requirements and design before coding starts.
Great for:

Rapid exploration and testing
Building when requirements are unclear

  CSS: 24
  EMOJI: 4

--- 详细列表 ---
 行号  类型             来源          详情                                      上下文
---------
  109  CSS              tool_input    overflow:auto x3                         .card { overflow-y: auto; ...
  115  EMOJI            text          发现 2 个 emoji: 📊💡                    使用📊图表展示数据...
```

**检查项**:
- `overflow:auto/scroll`（PPTX 转换致命问题）
- emoji 字符（PPT 中不应有 emoji）
- `!important`（过度使用说明样式冲突）
- 大文件输入/输出（>50KB 的工具输入，>100KB 的工具输出）

---

### 维度 7: 降级决策追踪

**脚本**: `07_degradation.py`
**目标**: 检查模型是否做了错误的降级决策。

```bash
python3 log_analysis/07_degradation.py logfile.jsonl
```

**搜索的关键词**（中英文双语）:
- 跳过/skip/省略
- 降级/degrade/fallback
- 简化/simplify/精简
- 截断/truncate
- 失败/无法/重试/retry
- 超出/too large/context limit/token limit

**输出示例**:
```
--- 助手消息中的降级决策 (按时间序) ---
 行号    时间  关键词        上下文
---------
  107  10:58  跳过          ...由于配图API不稳定，跳过图标匹配步骤...
  109  10:59  简化          ...简化处理，使用纯CSS装饰替代图标...
```

**常见错误模式**:
- **过度泛化**：A 失败 → 错误地跳过与 A 无关的 B（如配图失败 → 跳过本地图标脚本）
- **错误因果**：网络 API 失败 → 跳过本地脚本
- **时间压力下跳步**：直接跳到后续步骤

---

### 维度 8: 框架行为分析

**脚本**: `08_error_pattern.py`
**目标**: 分析 error 前后的消息模式，区分模型问题 vs 框架问题。

```bash
python3 log_analysis/08_error_pattern.py logfile.jsonl
```

**输出示例**:
```
--- 时间间隔分布 ---
  最大间隔: 600.0s
  平均间隔: 14.2s
  >30s 的间隔: 8
  >60s 的间隔: 3

================================================================================
错误事件 @ 行 41 (02:30:33): role=assistant stop=error type=msg

  --- 错误前 5 条 ---
  [15] 行   38  02:29:45  (-48s)    assistant   msg             toolUse       in= 43847  tools=exec
  [16] 行   39  02:29:57  (-36s)    toolResult  msg                           in=     0  tools=
  [17] 行   40  02:30:21  (-12s)    assistant   msg             toolUse       in= 43692  tools=write

  --- 错误后 5 条 ---
  [18] 行   41  02:30:33  (+0s)     assistant   msg             error         in=     0  tools= <<<
  [19] 行   42  02:35:45  (+312s)   assistant   msg             toolUse       in= 44102  tools=read

模式分析汇总:
  最大连续错误数: 1
  行 41: 错误前有 12s 的长间隔 (可能是超时)
  错误前常见工具: {'exec': 3, 'write': 2, 'read': 1}
```

**核心逻辑**:
- 构建统一的事件流（消息 + 系统事件 + compaction）
- 对每个 error 事件，展示前后各 5 条消息和时间间隔
- 分析连续错误（重试循环）、超长间隔（超时）、错误时的 token 使用
- 统计错误前常见的工具调用模式

**判断标准**:
- error 后自动恢复（<30s）→ 框架重试机制正常
- error 后需用户消息才恢复 → 框架重试失败
- error 前有 >60s 间隔 → 可能是超时触发
- error 时 usage=0 → API 连接层问题，非模型问题

---

### 维度 9: Pipeline 进度追踪

**脚本**: `09_pipeline.py`
**目标**: 确定任务走到了 Pipeline 哪一步，在哪里中断。

```bash
python3 log_analysis/09_pipeline.py logfile.jsonl
```

**检测逻辑**（按阶段匹配特征）:

| 阶段 | 工具模式 | 文件模式 | 脚本模式 |
|------|---------|---------|---------|
| Step1:研究搜索 | web_search | search_result | web_search.py |
| Step2:大纲生成 | — | outline | — |
| Step3:风格选择 | — | style/theme | extract_style.py |
| Step4:HTML生成 | write | slide*.html | — |
| Step5:SVG转换 | — | *.svg, *.png | html2svg.py, generate_image.py |
| Step6:PPTX打包 | — | *.pptx | svg2pptx.py |

**输出示例**:
```
阶段时间线概要
==============================
阶段                  开始时间    事件数  状态
------------------------------------------------------------
Step1:研究搜索          10:22:41       8  OK
Step2:大纲生成          10:29:02       3  OK
Step3:风格选择          10:40:15       6  OK
Step4:HTML生成          10:58:30      18  OK
Step5:SVG转换           11:12:05       2  OK
Step6:PPTX打包              ---        0  MISSING
```

---

### 维度 10: 根因汇总报告

**脚本**: `10_summary.py`
**目标**: 一键综合所有维度，输出结论性报告。

```bash
python3 log_analysis/10_summary.py logfile.jsonl
```

**输出示例**:
```
================================================================================
              JSONL 日志根因分析汇总报告
================================================================================

[1] 基本信息
  日志格式:     新格式(OpenClaw)
  模型:         step-3.5-flash
  总行数:       162
  开始时间:     2026-03-26 02:22:41
  结束时间:     2026-03-26 03:13:15
  总时长:       50.5 分钟

[2] Token 消耗
  API 调用次数:     77
  总输入 tokens:    4,491,796
  总输出 tokens:    70,787
  最大输入 tokens:  111,937
  上下文趋势:      上升 (前半均值=45,000 后半均值=85,000)

[3] 停止原因分布
  toolUse: 70
  stop: 2
  error: 5

[4] 错误和异常
  错误总数:     5
  Compaction:   1

[5] 工具使用统计
  exec                  18  (24.0%)  ########
  read                  15  (20.0%)  ######
  write                 12  (16.0%)  #####

[6] 质量问题
  Emoji 出现次数:    4
  CSS 违规次数:      24
  降级关键词出现:    8

[7] Pipeline 阶段检测
  Step1(研究搜索): OK (8 次)
  Step6(PPTX打包): 未检测到 (0 次)

================================================================================
[8] 根因推断
================================================================================
  1. 上下文膨胀: 最大 input tokens 达到 111,937
  2. CSS 违规 (24 次): overflow/position 问题需要在 prompt 中约束
  3. Emoji 出现 (4 次): PPT 中不应有 emoji
  4. Pipeline 阶段缺失: Step6 未被检测到
```

**自动推断规则**:
- 最大 input > 100K → 上下文膨胀警告
- compaction > 2 → 上下文反复膨胀
- 错误率 > 10% → 高错误率警告
- CSS 违规 > 0 → Prompt 约束不足
- Pipeline 阶段缺失 → 任务未完成

---

## 完整分析流程（SOP）

### 第一轮：快速诊断

```bash
# 1. 一键汇总（30秒了解全貌）
python3 log_analysis/10_summary.py log.jsonl

# 2. 看汇总报告的 [8] 根因推断，确定主要问题方向
```

### 第二轮：深入分析

根据第一轮发现的问题，选择对应脚本：

| 如果发现... | 运行... |
|------------|--------|
| 大量 error/terminated | `02_errors.py` + `08_error_pattern.py` |
| 上下文膨胀 | `03_context_growth.py` + `05_tool_stats.py` |
| CSS/Emoji 质量问题 | `06_quality_check.py` |
| 降级/跳过步骤 | `07_degradation.py` |
| Pipeline 未完成 | `09_pipeline.py` |
| 需要看完整执行流 | `01_timeline.py` |

### 第三轮：修复验证

```bash
# 修复后再跑一次，对比两次日志
python3 log_analysis/04_compare.py old_log.jsonl new_log.jsonl
```

---

## 迭代改进循环

```
分析日志 → 发现问题 → 定位根因 → 实施修复 → 再次测试 → 分析新日志 → ...
    ↑                                                          ↓
    └──────────────── 量化对比(04_compare.py) ←────────────────┘
```

每次迭代聚焦最大的瓶颈（帕累托原则）：

| 迭代 | 聚焦 | 发现 | 修复 | 验证 |
|------|------|------|------|------|
| 第一次 | length 截断 | prompts.md 全量读入(30KB) | 拆分为5文件 + 分批策略 | length 从4次→0次 |
| 第二次 | 时间瓶颈 | 配图占44%时长(17min) | 改为 opt-in | 预期50min→28min |
| 第二次 | 输出质量 | overflow-y:auto(13/20页) | CSS 禁止清单增补 | 待验证 |
| 第二次 | 降级错误 | 图标系统被跳过 | 标注"本地脚本不可跳过" | 待验证 |
