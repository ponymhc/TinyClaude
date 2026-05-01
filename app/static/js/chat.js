// ========== Chat Logic ==========
// _sseState 已在 state.js 中声明，此处复用全局变量

function handleSSEEvent(event, container) {
  const s = _sseState;
  switch (event.type) {
    case 'turn_start':
      _sseState = { thinkingEl: null, aiTextEl: null, pendingToolBlocks: {} };
      break;
    case 'token':
      if (event.thinking) {
        if (!s.thinkingEl) {
          s.thinkingEl = document.createElement('div');
          s.thinkingEl.className = 'msg-thinking';
          const label = document.createElement('div');
          label.className = 'msg-thinking-label';
          label.textContent = '思考中...';
          s.thinkingEl.appendChild(label);
          s.thinkingContent = document.createElement('div');
          s.thinkingContent.className = 'msg-thinking-content';
          s.thinkingEl.appendChild(s.thinkingContent);
          container.appendChild(s.thinkingEl);
        }
        s.thinkingContent.textContent += event.content;
      } else {
        if (s.thinkingEl) s.thinkingEl = null;
        if (!s.aiTextEl) {
          s.aiTextEl = document.createElement('div');
          s.aiTextEl.className = 'msg-ai';
          s.aiTextRaw = '';
          container.appendChild(s.aiTextEl);
        }
        s.aiTextRaw += event.content;
        if (!s._renderPending) {
          s._renderPending = true;
          requestAnimationFrame(() => {
            if (s.aiTextEl) {
              s.aiTextEl.innerHTML = marked.parse(s.aiTextRaw);
            }
            s._renderPending = false;
          });
        }
      }
      scrollToBottom();
      break;
    case 'tool_call_name':
      s.thinkingEl = null;
      if (!s.pendingToolBlocks) s.pendingToolBlocks = {};
      const idx = event.index ?? 0;
      if (!s.pendingToolBlocks[idx]) {
        const block = createToolBlock(event.tool, '');
        s.pendingToolBlocks[idx] = { block, inputText: '' };
        container.appendChild(block);
      }
      const nameEl = s.pendingToolBlocks[idx].block.querySelector('.msg-tool-name');
      if (nameEl) nameEl.textContent = event.tool;
      scrollToBottom();
      break;
    case 'tool_call_args':
      if (s.pendingToolBlocks) {
        const idx = event.index ?? 0;
        if (s.pendingToolBlocks[idx]) {
          s.pendingToolBlocks[idx].inputText += event.args;
          const inputEl = s.pendingToolBlocks[idx].block.querySelector('.msg-tool-content');
          if (inputEl && !inputEl.dataset.resultSlot) {
            inputEl.textContent = s.pendingToolBlocks[idx].inputText;
          }
          scrollToBottom();
        }
      }
      break;
    case 'tool_start':
      s.thinkingEl = null;
      const toolIdx = event.index ?? 0;
      if (s.pendingToolBlocks && s.pendingToolBlocks[toolIdx]) {
        const existingBlock = s.pendingToolBlocks[toolIdx].block;
        const inputEl = existingBlock.querySelector('.msg-tool-content');
        if (inputEl && !inputEl.dataset.resultSlot) {
          inputEl.textContent = event.input;
        }
        s.currentToolEl = existingBlock;
        delete s.pendingToolBlocks[toolIdx];
      } else {
        s.currentToolEl = createToolBlock(event.tool, event.input);
        container.appendChild(s.currentToolEl);
      }
      scrollToBottom();
      break;
    case 'tool_end':
      if (s.currentToolEl) {
        fillToolResult(s.currentToolEl, event.output);
      }
      break;
    case 'new_response':
      s.aiTextEl = null;
      s.thinkingEl = null;
      break;
    case 'done':
      if (s.aiTextEl && s.aiTextRaw !== undefined) {
        s.aiTextEl.innerHTML = marked.parse(s.aiTextRaw);
      }
      break;
    case 'warning':
      console.warn('Token budget warning:', event.content);
      break;
    case 'error':
      if (!s.aiTextEl) {
        s.aiTextEl = document.createElement('div');
        s.aiTextEl.className = 'msg-ai';
        s.aiTextEl.style.color = 'var(--danger)';
        container.appendChild(s.aiTextEl);
      }
      s.aiTextEl.textContent = '错误: ' + (event.content || '未知错误');
      break;
    case 'cancelled':
      if (s.aiTextEl && s.aiTextRaw) {
        s.aiTextEl.innerHTML = marked.parse(s.aiTextRaw);
      } else if (!s.aiTextEl) {
        s.aiTextEl = document.createElement('div');
        s.aiTextEl.className = 'msg-ai';
        s.aiTextEl.style.color = 'var(--danger)';
        s.aiTextEl.textContent = '（已取消）';
        container.appendChild(s.aiTextEl);
      }
      break;
  }
}

async function sendMessage() {
  const input = document.getElementById('inputBox');
  const message = input.value.trim();
  if (!message || isStreaming) return;

  input.value = '';
  autoResize(input);
  setStreamingState(true);
  appendUserMessage(message);

  const empty = document.getElementById('emptyState');
  if (empty) empty.remove();

  const { row, inner } = createAiContainer();
  currentAiContainer = inner;
  const typingIndicator = document.createElement('div');
  typingIndicator.className = 'msg-ai typing-indicator';
  typingIndicator.textContent = '思考中...';
  typingIndicator.style.color = 'var(--text-thinking)';
  currentAiContainer.appendChild(typingIndicator);
  document.getElementById('messagesContainer').appendChild(row);
  scrollToBottom();

  try {
    const resp = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: currentSessionId }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      if (typingIndicator.parentNode) typingIndicator.remove();
      const errEl = document.createElement('div');
      errEl.className = 'msg-ai';
      errEl.style.color = 'var(--danger)';
      errEl.textContent = `请求失败 (${resp.status}): ${errText}`;
      currentAiContainer.appendChild(errEl);
      scrollToBottom();
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let firstEvent = true;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        const lines = part.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const event = JSON.parse(jsonStr);
            if (firstEvent) {
              firstEvent = false;
              if (typingIndicator.parentNode) typingIndicator.remove();
            }
            handleSSEEvent(event, currentAiContainer);
          } catch (e) {
            console.warn('SSE parse error:', e, 'line:', line);
          }
        }
      }
    }

    if (firstEvent && typingIndicator.parentNode) {
      typingIndicator.remove();
    }
    if (currentAiContainer && currentAiContainer.children.length === 0) {
      const emptyEl = document.createElement('div');
      emptyEl.className = 'msg-ai';
      emptyEl.style.color = 'var(--text-thinking)';
      emptyEl.textContent = '（未收到回复）';
      currentAiContainer.appendChild(emptyEl);
    }
  } catch (e) {
    console.error('Chat error:', e);
  } finally {
    setStreamingState(false);
    currentAiContainer = null;
    await refreshSessionList();
    loadHistory();
  }
}

function setStreamingState(streaming) {
  isStreaming = streaming;
  const btnSend = document.getElementById('btnSend');
  const btnStop = document.getElementById('btnStop');
  const btnNew = document.getElementById('btnNewSession');
  const indicator = document.getElementById('streamingIndicator');
  if (streaming) {
    btnSend.classList.add('hidden');
    btnStop.classList.add('active');
    btnNew.disabled = true;
    indicator.classList.add('active');
    document.querySelectorAll('.session-item-delete').forEach(b => b.disabled = true);
  } else {
    btnSend.classList.remove('hidden');
    btnStop.classList.remove('active');
    btnNew.disabled = false;
    indicator.classList.remove('active');
    document.querySelectorAll('.session-item-delete').forEach(b => b.disabled = false);
  }
}

async function cancelGeneration() {
  try {
    await fetch(`${API}/api/chat/cancel`, { method: 'POST' });
  } catch (e) {
    console.error('Failed to cancel:', e);
  }
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!isStreaming) sendMessage();
  }
}