// ========== UI Components ==========
function createAiContainer() {
  const row = document.createElement('div');
  row.className = 'msg-row ai';
  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar ai-avatar';
  avatar.textContent = 'AI';
  const body = document.createElement('div');
  body.className = 'msg-body';
  const inner = document.createElement('div');
  inner.className = 'msg-ai-container';
  body.appendChild(inner);
  row.appendChild(avatar);
  row.appendChild(body);
  return { row, inner };
}

function appendUserMessage(text) {
  const container = document.getElementById('messagesContainer');
  const row = document.createElement('div');
  row.className = 'msg-row user';
  const body = document.createElement('div');
  body.className = 'msg-body';
  const bubble = document.createElement('div');
  bubble.className = 'msg-user';
  bubble.textContent = text;
  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar user-avatar';
  avatar.textContent = 'U';
  body.appendChild(bubble);
  row.appendChild(body);
  row.appendChild(avatar);
  container.appendChild(row);
  scrollToBottom();
}

function appendAiText(container, text) {
  const el = document.createElement('div');
  el.className = 'msg-ai';
  el.innerHTML = marked.parse(text);
  container.appendChild(el);
}

function createToolBlock(toolName, input) {
  const block = document.createElement('div');
  block.className = 'msg-tool';

  const header = document.createElement('div');
  header.className = 'msg-tool-header';
  header.innerHTML = `
    <span class="msg-tool-icon">🔧</span>
    <span class="msg-tool-name">${escapeHtml(toolName)}</span>
    <span class="msg-tool-toggle">▶</span>
  `;

  const body = document.createElement('div');
  body.className = 'msg-tool-body';

  const inputLabel = document.createElement('div');
  inputLabel.className = 'msg-tool-label';
  inputLabel.textContent = '输入';
  const inputContent = document.createElement('div');
  inputContent.className = 'msg-tool-content';
  inputContent.textContent = input || '(空)';

  const resultLabel = document.createElement('div');
  resultLabel.className = 'msg-tool-label';
  resultLabel.textContent = '输出';
  const resultContent = document.createElement('div');
  resultContent.className = 'msg-tool-content';
  resultContent.textContent = '加载中...';
  resultContent.dataset.resultSlot = 'true';

  body.appendChild(inputLabel);
  body.appendChild(inputContent);
  body.appendChild(resultLabel);
  body.appendChild(resultContent);

  header.addEventListener('click', () => {
    body.classList.toggle('expanded');
    header.querySelector('.msg-tool-toggle').classList.toggle('expanded');
  });

  block.appendChild(header);
  block.appendChild(body);
  return block;
}

function fillToolResult(toolBlock, output) {
  const slot = toolBlock.querySelector('[data-result-slot]');
  if (slot) {
    slot.textContent = output || '(空)';
  }
}