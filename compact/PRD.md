# Compact 模块 PRD - Claude Code CLI 对齐

## 1. 概述

### 1.1 目标
将 TinyClaude 的 compact 模块重新设计，与 Claude Code CLI 的压缩功能保持一致。主要使用 Session Memory 文件作为压缩摘要来源，替代传统的 LLM 摘要生成。

### 1.2 参考实现
Claude Code CLI: `services/compact/` 目录下的压缩模块

### 1.3 核心文件
| Claude Code CLI | 描述 |
|----------------|------|
| `compact.ts` | 核心压缩逻辑，生成 LLM 摘要 |
| `sessionMemoryCompact.ts` | Session Memory 压缩（实验性） |
| `microCompact.ts` | 微压缩，清理旧的工具结果 |
| `autoCompact.ts` | 自动压缩协调器 |
| `compactWarningState.ts` | 压缩警告状态管理 |
| `prompt.ts` | 压缩摘要提示模板 |
| `grouping.ts` | 消息分组 |

---

## 2. 压缩类型

### 2.1 自动压缩 (Auto Compact)
**触发条件**: 上下文 token 数达到阈值
- **阈值计算**: `effectiveContextWindow - 13_000` (默认约 187K tokens)
- **阈值缓冲**:
  - 自动压缩缓冲: 13,000 tokens
  - 警告阈值缓冲: 20,000 tokens
  - 手动压缩缓冲: 3,000 tokens

**执行流程**:
1. 优先尝试 Session Memory 压缩
2. 失败则使用传统 LLM 压缩

### 2.2 手动压缩 (Manual Compact)
用户通过 `/compact` 命令触发

### 2.3 部分压缩 (Partial Compact)
**方向 `from`**: 总结指定消息之后的内容，保留之前的消息
- 保留消息的 prompt cache 被保留

**方向 `up_to`**: 总结指定消息之前的内容，保留之后的消息
- 摘要放在前面，prompt cache 失效

### 2.4 微压缩 (Micro Compact)
清理旧的工具结果，释放 token 空间。

**两种模式**:
1. **时间基础微压缩**: 当距离最后一条 assistant 消息超过阈值时，清理除最近 N 条之外的所有工具结果
2. **缓存微压缩**: 使用 API 的 cache_editing 功能，不修改本地消息内容

---

## 3. Session Memory 压缩

### 3.1 概述
使用 Session Memory 文件（会话笔记）作为压缩摘要，替代 LLM 生成摘要。

### 3.2 配置
```typescript
type SessionMemoryCompactConfig = {
  minTokens: number              // 保留最小 token 数，默认 10,000
  minTextBlockMessages: number   // 保留最小文本消息数，默认 5
  maxTokens: number              // 保留最大 token 数（硬上限），默认 40,000
}
```

### 3.3 判断条件
必须同时满足：
1. `tengu_session_memory` 功能标志开启
2. `tengu_sm_compact` 功能标志开启
3. Session Memory 已初始化（有实际内容，非模板）

### 3.4 压缩流程
```
trySessionMemoryCompaction()
├── 检查 shouldUseSessionMemoryCompaction()
├── 等待 Session Memory 提取完成 (waitForSessionMemoryExtraction)
├── 获取 lastSummarizedMessageId
├── 获取 Session Memory 内容
│
├── 计算保留消息起始索引 (calculateMessagesToKeepIndex)
│   ├── 从 lastSummarizedIndex + 1 开始
│   ├── 向后扩展直到满足 minTokens + minTextBlockMessages
│   └── 硬上限 maxTokens
│
├── 调整索引保持 API 不变量 (adjustIndexToPreserveAPIInvariants)
│   ├── Step 1: 处理 tool_use/tool_result 配对
│   └── Step 2: 处理共享 message.id 的 thinking blocks
│
├── 过滤旧压缩边界消息
├── 创建压缩边界消息 (createCompactBoundaryMessage)
├── 截断 Session Memory 内容 (truncateSessionMemoryForCompact)
├── 创建摘要消息 (getCompactUserSummaryMessage)
├── 执行 SessionStart hooks (processSessionStartHooks)
└── 返回 CompactionResult
```

### 3.5 消息保留计算
```typescript
calculateMessagesToKeepIndex(messages, lastSummarizedIndex):
  1. startIndex = lastSummarizedIndex + 1
  2. 计算从 startIndex 到末尾的 totalTokens 和 textBlockCount
  3. 如果达到 maxTokens 或满足 minTokens + minTextBlockMessages，停止
  4. 向前扩展直到满足条件或达到 floor（最后一个压缩边界之后）
  5. 调整索引保持 API 不变量
```

### 3.6 API 不变量保持
```typescript
adjustIndexToPreserveAPIInvariants(messages, startIndex):

// Step 1: 处理 tool_use/tool_result 配对
// 如果保留的消息中有 tool_result，需要包含对应的 tool_use
allToolResultIds = 收集 startIndex 到末尾的所有 tool_result IDs
neededToolUseIds = 过滤已在保留范围内的 tool_use IDs
向后查找包含 neededToolUseIds 的 assistant 消息

// Step 2: 处理共享 message.id 的 thinking blocks
// 流式输出会产生分块消息：
// Index N:   assistant, message.id: X, content: [thinking]
// Index N+1: assistant, message.id: X, content: [tool_use]
// 如果 startIndex = N+1，需要包含 N 的 thinking block 才能正确合并
messageIdsInKeptRange = 收集保留范围内所有 assistant 消息的 message.id
向后查找有共享 message.id 的 assistant 消息
```

---

## 4. 传统压缩 (LLM Summary)

### 4.1 概述
使用 LLM 生成对话摘要，替换旧的对话历史。

### 4.2 摘要提示模板
Claude Code CLI 使用 `<analysis>` 和 `<summary>` 结构的提示：

```xml
<analysis>
[分析过程：按时间顺序分析每条消息，识别用户请求、关键决策、技术细节等]
</analysis>

<summary>
1. Primary Request and Intent: 用户明确请求
2. Key Technical Concepts: 技术概念列表
3. Files and Code Sections: 文件和代码片段
4. Errors and fixes: 错误和修复
5. Problem Solving: 问题解决
6. All user messages: 所有用户消息
7. Pending Tasks: 待处理任务
8. Current Work: 当前工作
9. Optional Next Step: 下一步
</summary>
```

### 4.3 摘要格式化
```typescript
formatCompactSummary(summary):
  1. 移除 <analysis> 标签和内容
  2. 提取 <summary> 标签内容
  3. 替换为可读的标题格式
```

### 4.4 执行流程
```
compactConversation()
├── 执行 PreCompact hooks
├── 构建压缩提示 (getCompactPrompt)
├── 尝试 Prompt Cache 共享（forked agent）
│   └── 失败则回退到普通流式
├── 流式获取摘要 (streamCompactSummary)
│   ├── 禁用 thinking
│   ├── 只允许 FileReadTool（或包含 ToolSearchTool）
│   └── 处理 PTL (Prompt Too Long) 重试
├── 提取摘要文本
├── 清理文件读取缓存
├── 创建 Post-compact attachments
│   ├── 文件附件 (createPostCompactFileAttachments)
│   ├── 技能附件 (createSkillAttachmentIfNeeded)
│   ├── 计划附件 (createPlanAttachmentIfNeeded)
│   └── 异步 Agent 附件
├── 执行 SessionStart hooks
├── 创建边界消息 (createCompactBoundaryMessage)
├── 创建摘要消息 (getCompactUserSummaryMessage)
└── 返回 CompactionResult
```

---

## 5. 消息处理

### 5.1 消息结构
```typescript
interface CompactionResult {
  boundaryMarker: SystemMessage          // 压缩边界标记
  summaryMessages: UserMessage[]        // 摘要消息
  attachments: AttachmentMessage[]      // 附件（文件、技能、计划等）
  hookResults: HookResultMessage[]      // Hook 结果
  messagesToKeep?: Message[]            // 保留的消息
  userDisplayMessage?: string           // 用户显示消息
  preCompactTokenCount?: number        // 压缩前 token 数
  postCompactTokenCount?: number       // 压缩后 token 数
  truePostCompactTokenCount?: number   // 真实压缩后 token 数
  compactionUsage?: TokenUsage         // 压缩 API 调用使用量
}
```

### 5.2 Post-compact Messages 构建
```typescript
buildPostCompactMessages(result):
  return [
    result.boundaryMarker,
    ...result.summaryMessages,
    ...(result.messagesToKeep ?? []),
    ...result.attachments,
    ...result.hookResults,
  ]
```

### 5.3 压缩边界消息
```typescript
createCompactBoundaryMessage(
  type: 'auto' | 'manual',
  preCompactTokenCount: number,
  lastMessageUuid?: string,
  customInstructions?: string,
  messagesSummarized?: number,
): SystemMessage

// 包含 compactMetadata
interface CompactMetadata {
  preservedSegment?: {
    headUuid: string      // 保留段头 UUID
    anchorUuid: string    // 锚点 UUID
    tailUuid: string      // 保留段尾 UUID
  }
  preCompactDiscoveredTools?: string[]  // 压缩前发现的工具
}
```

### 5.4 保留段注释
```typescript
annotateBoundaryWithPreservedSegment(
  boundary: SystemCompactBoundaryMessage,
  anchorUuid: UUID,
  messagesToKeep: Message[],
): SystemCompactBoundaryMessage

// 用于消息链重建：
// - suffix-preserving (reactive/session-memory): anchorUuid = last summary message
// - prefix-preserving (partial compact): anchorUuid = boundary itself
```

---

## 6. Post-compact Attachments

### 6.1 文件附件
```typescript
createPostCompactFileAttachments(
  readFileState: Record<string, { content: string; timestamp: number }>,
  context: ToolUseContext,
  maxFiles: number = 5,
  preservedMessages: Message[] = [],
): Promise<AttachmentMessage[]>

// 选择最近访问的文件（按时间排序）
// 跳过已存在于保留消息中的文件路径
// 跳过 plan 和 memory 文件
// Token 预算: 50,000 tokens 总计，每文件最多 5,000 tokens
```

### 6.2 技能附件
```typescript
createSkillAttachmentIfNeeded(
  agentId?: string,
): AttachmentMessage | null

// Token 预算: 25,000 tokens，每技能最多 5,000 tokens
// 按最近调用时间排序
```

### 6.3 计划附件
```typescript
createPlanAttachmentIfNeeded(
  agentId?: AgentId,
): AttachmentMessage | null
```

### 6.4 异步 Agent 附件
```typescript
createAsyncAgentAttachmentsIfNeeded(
  context: ToolUseContext,
): Promise<AttachmentMessage[]>

// 包含仍在运行或未检索的后台 Agent
```

---

## 7. 压缩阈值

### 7.1 上下文窗口
```typescript
getContextWindowForModel(model: string): number

// 根据模型返回上下文窗口大小
// Claude 3.5 Sonnet: 200K tokens
// Claude 3 Opus: 200K tokens
// ...
```

### 7.2 有效上下文窗口
```typescript
getEffectiveContextWindowSize(model: string): number
// = getContextWindowForModel(model) - MAX_OUTPUT_TOKENS_FOR_SUMMARY
// MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20,000
```

### 7.3 自动压缩阈值
```typescript
getAutoCompactThreshold(model: string): number
// = getEffectiveContextWindowSize(model) - AUTOCOMPACT_BUFFER_TOKENS (13,000)
```

### 7.4 Token 警告状态
```typescript
calculateTokenWarningState(tokenUsage: number, model: string):
// percentLeft: 剩余百分比
// isAboveWarningThreshold: 是否超过警告阈值
// isAboveErrorThreshold: 是否超过错误阈值
// isAboveAutoCompactThreshold: 是否触发自动压缩
// isAtBlockingLimit: 是否达到阻塞限制
```

---

## 8. Hooks

### 8.1 PreCompact Hooks
```typescript
executePreCompactHooks(
  trigger: 'auto' | 'manual',
  customInstructions?: string | null,
  signal?: AbortSignal,
): Promise<HookResult>

// 返回: { newCustomInstructions?, userDisplayMessage? }
```

### 8.2 PostCompact Hooks
```typescript
executePostCompactHooks(
  trigger: 'auto' | 'manual',
  compactSummary?: string,
  signal?: AbortSignal,
): Promise<HookResult>
```

### 8.3 SessionStart Hooks
```typescript
processSessionStartHooks(
  trigger: 'compact' | 'manual',
  options: { model: string },
): Promise<HookResultMessage[]>

// 用于恢复 CLAUDE.md 等上下文
```

---

## 9. 微压缩 (Micro Compact)

### 9.1 时间基础微压缩
```typescript
// 当距离最后 assistant 消息超过阈值时触发
// 清理除最近 N 条之外的所有可压缩工具结果
// 可压缩工具: FileRead, Bash, Grep, Glob, WebSearch, WebFetch, Edit, Write
```

### 9.2 缓存微压缩
```typescript
// 使用 API 的 cache_editing 功能
// 不修改本地消息内容
// 在 API 层添加 cache_reference 和 cache_edits
```

### 9.3 触发条件
```typescript
evaluateTimeBasedTrigger(messages, querySource):
// 距离阈值 (gapThresholdMinutes): 默认 5 分钟
// 只在主线程触发
// 必须有 assistant 消息
```

---

## 10. 错误处理

### 10.1 PTL 重试 (Prompt Too Long)
```typescript
truncateHeadForPTLRetry(messages, ptlResponse):
// 当压缩请求本身超出上下文时触发
// 丢弃最老的 API round 分组直到覆盖 tokenGap
// 最多重试 3 次
// 回退: 丢弃 20% 的分组
```

### 10.2 错误消息
```typescript
ERROR_MESSAGE_NOT_ENOUGH_MESSAGES = "Not enough messages to compact."
ERROR_MESSAGE_PROMPT_TOO_LONG = "Conversation too long. Press esc twice to go up a few messages and try again."
ERROR_MESSAGE_USER_ABORT = "API Error: Request was aborted."
ERROR_MESSAGE_INCOMPLETE_RESPONSE = "Compaction interrupted. This may be due to network issues — please try again."
```

### 10.3 断路器
```typescript
// 连续失败 3 次后停止自动压缩尝试
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
```

---

## 11. 会话状态管理

### 11.1 压缩跟踪状态
```typescript
type AutoCompactTrackingState = {
  compacted: boolean
  turnCounter: number
  turnId: string           // 每轮唯一 ID
  consecutiveFailures?: number
}
```

### 11.2 压缩后标记
```typescript
markPostCompaction()
// 在 state 中标记已执行过压缩
```

### 11.3 Session Memory UUID 追踪
```typescript
setLastSummarizedMessageId(messageId: string | undefined)
// 在 Session Memory 压缩后重置
```

---

## 12. 环境变量

| 变量 | 描述 |
|------|------|
| `DISABLE_COMPACT` | 禁用所有压缩 |
| `DISABLE_AUTO_COMPACT` | 只禁用自动压缩 |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 覆盖自动压缩窗口 |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | 覆盖自动压缩阈值（百分比） |
| `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE` | 覆盖阻塞限制 |
| `ENABLE_CLAUDE_CODE_SM_COMPACT` | 强制启用 Session Memory 压缩 |
| `DISABLE_CLAUDE_CODE_SM_COMPACT` | 强制禁用 Session Memory 压缩 |

---

## 13. 待实现功能

### 13.1 必须实现
- [ ] 核心压缩逻辑 (`compact.py`)
- [ ] Session Memory 压缩 (`session_memory_compact.py`)
- [ ] 自动压缩协调器 (`auto_compact.py`)
- [ ] 微压缩 (`micro_compact.py`)
- [ ] 压缩警告 (`compact_warning.py`)
- [ ] 消息分组 (`grouping.py`)

### 13.2 可选实现
- [ ] Prompt Cache 共享 (forked agent)
- [ ] Post-compact 文件附件
- [ ] Post-compact 技能附件
- [ ] Post-compact 计划附件
- [ ] 异步 Agent 附件
- [ ] PTL 重试机制

---

## 14. 文件结构

```
compact/
├── __init__.py                    # 模块导出
├── compact.py                      # 核心压缩逻辑（LLM 摘要）
├── session_memory_compact.py       # Session Memory 压缩
├── auto_compact.py                # 自动压缩协调器
├── micro_compact.py               # 微压缩
├── compact_warning.py              # 压缩警告
├── grouping.py                    # 消息分组
├── prompt.py                      # 压缩提示模板
├── config.py                      # 配置管理
└── types.py                      # 类型定义
```

---

## 15. API 设计

### 15.1 核心函数
```python
# 压缩
async def compact_conversation(
    messages: List[Message],
    context: ToolUseContext,
    cache_safe_params: CacheSafeParams,
    suppress_follow_up_questions: bool,
    custom_instructions: Optional[str] = None,
    is_auto_compact: bool = False,
) -> CompactionResult:

# Session Memory 压缩
async def try_session_memory_compaction(
    messages: List[Message],
    agent_id: Optional[str] = None,
    auto_compact_threshold: Optional[int] = None,
) -> Optional[CompactionResult]:

# 自动压缩
async def auto_compact_if_needed(
    messages: List[Message],
    tool_use_context: ToolUseContext,
    cache_safe_params: CacheSafeParams,
    query_source: Optional[str] = None,
    tracking: Optional[AutoCompactTrackingState] = None,
) -> AutoCompactResult:

# 微压缩
async def microcompact_messages(
    messages: List[Message],
    tool_use_context: Optional[ToolUseContext] = None,
    query_source: Optional[str] = None,
) -> MicrocompactResult:
```

### 15.2 配置函数
```python
def get_auto_compact_threshold(model: str) -> int:
def get_effective_context_window_size(model: str) -> int:
def calculate_token_warning_state(token_usage: int, model: str) -> TokenWarningState:
def is_auto_compact_enabled() -> bool:
```

---

## 16. 关键算法

### 16.1 消息保留索引计算
```
输入: messages[], lastSummarizedIndex
输出: startIndex

1. startIndex = lastSummarizedIndex + 1
2. 计算 totalTokens 和 textBlockCount
3. 如果 totalTokens >= maxTokens → 返回 adjustIndex()
4. 如果 totalTokens >= minTokens AND textBlockCount >= minTextBlockMessages → 返回 adjustIndex()
5. floor = 最后一个压缩边界的索引 + 1
6. 从 startIndex - 1 向后遍历到 floor
   - 累加 totalTokens 和 textBlockCount
   - 如果达到 maxTokens → 停止
   - 如果达到 minTokens + minTextBlockMessages → 停止
7. 返回 adjustIndex()
```

### 16.2 API 不变量调整
```
输入: messages[], startIndex
输出: adjustedIndex

Step 1: tool_use/tool_result 配对
1. 收集 startIndex 到末尾的所有 tool_result IDs
2. 过滤已在保留范围内的 tool_use IDs
3. 向后查找需要的 tool_use
4. 调整 adjustedIndex

Step 2: 共享 message.id
1. 收集保留范围内所有 assistant 消息的 message.id
2. 向后查找有共享 message.id 的 assistant 消息
3. 调整 adjustedIndex

返回 adjustedIndex
```
