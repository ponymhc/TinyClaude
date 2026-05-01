// ========== Session Management ==========
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('active');
}

async function loadSessions() {
  try {
    const resp = await fetch(`${API}/api/sessions`);
    const data = await resp.json();
    renderSessionList(data.sessions, data.current);
    currentSessionId = data.current;
    updateUIState();
    if (currentSessionId) {
      await loadSessionMessages(currentSessionId);
      loadHistory();
    }
    updateSessionTitle();
  } catch (e) {
    console.error('Failed to load sessions:', e);
  }
}

async function refreshSessionList() {
  try {
    const resp = await fetch(`${API}/api/sessions`);
    const data = await resp.json();
    renderSessionList(data.sessions, data.current);
    currentSessionId = data.current;
    updateUIState();
    updateSessionTitle();
    loadHistory();
  } catch (e) {
    console.error('Failed to refresh sessions:', e);
  }
}

function updateUIState() {
  const hasSession = !!currentSessionId;
  document.getElementById('inputArea').style.display = hasSession ? 'flex' : 'none';
  const noSession = document.getElementById('noSessionState');
  if (noSession) {
    noSession.style.display = hasSession ? 'none' : 'flex';
  }
}

function renderSessionList(sessions, activeId) {
  const list = document.getElementById('sessionList');
  list.innerHTML = '';
  sessions.forEach(s => {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.session_id === activeId ? ' active' : '');
    item.dataset.id = s.session_id;
    item.innerHTML = `
      <span class="session-item-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
      <button class="session-item-delete" onclick="event.stopPropagation(); deleteSession('${s.session_id}')" ${isStreaming ? 'disabled' : ''} title="删除会话">×</button>
    `;
    item.addEventListener('click', () => switchSession(s.session_id));
    list.appendChild(item);
  });
}

async function createNewSession() {
  if (isStreaming) return;
  try {
    const resp = await fetch(`${API}/api/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await resp.json();
    currentSessionId = data.session_id;
    document.getElementById('messagesContainer').innerHTML = '<div class="empty-state" id="emptyState">开始新的对话</div>';
    await refreshSessionList();
    closeSidebarMobile();
  } catch (e) {
    console.error('Failed to create session:', e);
  }
}

async function switchSession(sessionId) {
  if (isStreaming || sessionId === currentSessionId) return;
  try {
    await fetch(`${API}/api/sessions/${sessionId}/load`, { method: 'POST' });
    currentSessionId = sessionId;
    await loadSessionMessages(sessionId);
    await refreshSessionList();
    closeSidebarMobile();
  } catch (e) {
    console.error('Failed to switch session:', e);
  }
}

async function deleteSession(sessionId) {
  if (isStreaming) return;
  if (!confirm('确定要删除此会话吗？')) return;
  try {
    await fetch(`${API}/api/sessions/${sessionId}`, { method: 'DELETE' });
    currentSessionId = null;
    await refreshSessionList();
    if (currentSessionId) {
      await loadSessionMessages(currentSessionId);
    } else {
      document.getElementById('messagesContainer').innerHTML =
        '<div class="no-session-state" id="noSessionState">' +
        '<div class="no-session-icon">💬</div>' +
        '<div class="no-session-text">请创建会话开始对话</div>' +
        '<button class="btn-no-session" onclick="createNewSession()">创建新会话</button>' +
        '</div>';
    }
    updateSessionTitle();
    closeSidebarMobile();
  } catch (e) {
    console.error('Failed to delete session:', e);
  }
}

async function loadSessionMessages(sessionId) {
  try {
    const resp = await fetch(`${API}/api/sessions/${sessionId}/messages`);
    const data = await resp.json();
    const container = document.getElementById('messagesContainer');
    container.innerHTML = '';
    if (!data.messages || data.messages.length === 0) {
      container.innerHTML = '<div class="empty-state" id="emptyState">开始新的对话</div>';
      return;
    }
    let lastTurnId = -1;
    let aiInner = null;
    for (const msg of data.messages) {
      if (msg.type === 'human') {
        aiInner = null;
        appendUserMessage(msg.content);
      } else if (msg.type === 'ai') {
        if (msg.turn_id !== lastTurnId) {
          const { row, inner } = createAiContainer();
          aiInner = inner;
          container.appendChild(row);
          lastTurnId = msg.turn_id;
        }
        const reasoning = msg.additional_kwargs && msg.additional_kwargs.reasoning_content;
        if (reasoning) {
          const thinkingEl = document.createElement('div');
          thinkingEl.className = 'msg-thinking';
          const label = document.createElement('div');
          label.className = 'msg-thinking-label';
          label.textContent = '思考中...';
          thinkingEl.appendChild(label);
          const thinkingContent = document.createElement('div');
          thinkingContent.className = 'msg-thinking-content';
          thinkingContent.textContent = reasoning;
          thinkingEl.appendChild(thinkingContent);
          aiInner.appendChild(thinkingEl);
        }
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          for (const tc of msg.tool_calls) {
            const toolBlock = createToolBlock(tc.name, JSON.stringify(tc.args, null, 2));
            aiInner.appendChild(toolBlock);
          }
        }
        if (msg.content) {
          appendAiText(aiInner, msg.content);
        }
      } else if (msg.type === 'tool') {
        if (aiInner) {
          const toolBlocks = aiInner.querySelectorAll('.msg-tool');
          const lastBlock = toolBlocks[toolBlocks.length - 1];
          if (lastBlock) {
            fillToolResult(lastBlock, msg.content);
          } else {
            const fallback = document.createElement('div');
            fallback.className = 'msg-ai';
            fallback.style.fontSize = '12px';
            fallback.style.color = 'var(--text-secondary)';
            fallback.textContent = '[工具结果] ' + msg.content;
            aiInner.appendChild(fallback);
          }
        }
      }
    }
    scrollToBottom();
  } catch (e) {
    console.error('Failed to load messages:', e);
  }
}

function updateSessionTitle() {
  const active = document.querySelector('.session-item.active .session-item-title');
  document.getElementById('sessionTitleText').textContent = active ? active.textContent : '新会话';
}

function closeSidebarMobile() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('active');
}

async function loadHistory() {
  if (!currentSessionId) {
    document.getElementById('historyList').innerHTML = '<div class="history-empty">暂无会话</div>';
    document.getElementById('historyCount').textContent = '';
    return;
  }
  try {
    const resp = await fetch(`${API}/api/sessions/${currentSessionId}/messages`);
    if (!resp.ok) return;
    const data = await resp.json();
    const msgs = data.messages || [];
    document.getElementById('historyCount').textContent = `(${msgs.length})`;
    if (msgs.length === 0) {
      document.getElementById('historyList').innerHTML = '<div class="history-empty">暂无消息</div>';
      return;
    }
    const toolNameMap = {};
    for (const m of msgs) {
      if (m.type === 'ai' && m.tool_calls) {
        for (const tc of m.tool_calls) {
          if (tc.id) toolNameMap[tc.id] = tc.name;
        }
      }
    }
    const recent = msgs.slice(-100).reverse();
    let html = '';
    for (const msg of recent) {
      if (msg.type === 'human') {
        const preview = msg.content.length > 80 ? msg.content.slice(0, 80) + '...' : msg.content;
        html += `<div class="history-item">
          <div class="history-item-role user">用户</div>
          <div class="history-item-content" title="${escapeHtml(msg.content)}">${escapeHtml(preview)}</div>
        </div>`;
      } else if (msg.type === 'ai') {
        if (!msg.content && msg.tool_calls) continue;
        const text = msg.content || '';
        if (!text) continue;
        const preview = text.length > 150 ? text.slice(0, 150) + '...' : text;
        html += `<div class="history-item">
          <div class="history-item-role ai">AI</div>
          <div class="history-item-content ai-content" title="${escapeHtml(text)}">${escapeHtml(preview)}</div>
        </div>`;
      } else if (msg.type === 'tool') {
        const toolName = toolNameMap[msg.tool_call_id] || '工具';
        const preview = msg.content.length > 60 ? msg.content.slice(0, 60) + '...' : msg.content;
        html += `<div class="history-item">
          <div class="history-item-role tool">${toolName}</div>
          <div class="history-item-content" title="${escapeHtml(msg.content)}">${escapeHtml(preview)}</div>
        </div>`;
      }
    }
    document.getElementById('historyList').innerHTML = html || '<div class="history-empty">暂无消息</div>';
    document.getElementById('historyList').scrollTop = 0;
  } catch (e) {
    console.error('Failed to load history:', e);
    document.getElementById('historyList').innerHTML = '<div class="history-empty">加载失败</div>';
  }
}