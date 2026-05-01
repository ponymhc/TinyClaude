// ========== File Manager ==========
async function refreshFiles() {
  if (document.getElementById('filePreview').classList.contains('active')) return;
  try {
    const resp = await fetch(`${API}/api/files?path=${encodeURIComponent(fileCurrentPath)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const hash = JSON.stringify(data.items.map(i => i.name + i.is_dir + i.size + i.path));
    if (hash === _lastFileListHash && data.current_path === fileCurrentPath) return;
    _lastFileListHash = hash;
    fileCurrentPath = data.current_path;
    renderBreadcrumb(fileCurrentPath, data.parent_path);
    const list = document.getElementById('fileList');
    if (data.items.length === 0) {
      list.innerHTML = '<div class="file-preview-empty">空目录</div>';
      return;
    }
    let html = '';
    if (data.parent_path !== null) {
      html += `<div class="file-item" onclick="loadDirectory('${escapeAttr(data.parent_path)}')">
        <span class="file-item-icon">⬆️</span>
        <span class="file-item-name">..</span>
      </div>`;
    }
    for (const item of data.items) {
      const icon = item.is_dir ? '📁' : getFileIcon(item.name);
      const sizeStr = item.is_dir ? '' : formatSize(item.size);
      const cls = item.is_dir ? 'file-item file-item-dir' : 'file-item';
      const action = item.is_dir
        ? `loadDirectory('${escapeAttr(item.path)}')`
        : (item.previewable ? `previewFile('${escapeAttr(item.path)}')` : '');
      html += `<div class="${cls}" onclick="${action}" ${!action ? 'style="opacity:0.5;cursor:default"' : ''}>
        <span class="file-item-icon">${icon}</span>
        <span class="file-item-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
        ${sizeStr ? `<span class="file-item-size">${sizeStr}</span>` : ''}
      </div>`;
    }
    list.innerHTML = html;
  } catch (e) { /* silent */ }
}

async function loadDirectory(path) {
  try {
    const resp = await fetch(`${API}/api/files?path=${encodeURIComponent(path)}`);
    if (!resp.ok) {
      document.getElementById('fileList').innerHTML = '<div class="file-preview-empty">加载失败</div>';
      return;
    }
    const data = await resp.json();
    fileCurrentPath = data.current_path;
    renderBreadcrumb(fileCurrentPath, data.parent_path);
    _lastFileListHash = JSON.stringify(data.items.map(i => i.name + i.is_dir + i.size + i.path));
    const list = document.getElementById('fileList');
    if (data.items.length === 0) {
      list.innerHTML = '<div class="file-preview-empty">空目录</div>';
      return;
    }
    let html = '';
    if (data.parent_path !== null) {
      html += `<div class="file-item" onclick="loadDirectory('${escapeAttr(data.parent_path)}')">
        <span class="file-item-icon">⬆️</span>
        <span class="file-item-name">..</span>
      </div>`;
    }
    for (const item of data.items) {
      const icon = item.is_dir ? '📁' : getFileIcon(item.name);
      const sizeStr = item.is_dir ? '' : formatSize(item.size);
      const cls = item.is_dir ? 'file-item file-item-dir' : 'file-item';
      const action = item.is_dir
        ? `loadDirectory('${escapeAttr(item.path)}')`
        : (item.previewable ? `previewFile('${escapeAttr(item.path)}')` : '');
      html += `<div class="${cls}" onclick="${action}" ${!action ? 'style="opacity:0.5;cursor:default"' : ''}>
        <span class="file-item-icon">${icon}</span>
        <span class="file-item-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
        ${sizeStr ? `<span class="file-item-size">${sizeStr}</span>` : ''}
      </div>`;
    }
    list.innerHTML = html;
    closeFilePreview();
  } catch (e) {
    console.error('Failed to load directory:', e);
  }
}

function renderBreadcrumb(currentPath) {
  const el = document.getElementById('fileBreadcrumb');
  if (!currentPath) {
    el.innerHTML = '<span>🏠</span>';
    return;
  }
  const parts = currentPath.split('/');
  let html = '<span onclick="loadDirectory(\'\')">🏠</span>';
  let accumulated = '';
  for (let i = 0; i < parts.length; i++) {
    accumulated += (i > 0 ? '/' : '') + parts[i];
    const p = accumulated;
    html += `<span class="sep">/</span><span onclick="loadDirectory('${escapeAttr(p)}')">${escapeHtml(parts[i])}</span>`;
  }
  el.innerHTML = html;
}

async function previewFile(path) {
  try {
    const resp = await fetch(`${API}/api/files/content?path=${encodeURIComponent(path)}`);
    if (!resp.ok) {
      const data = await resp.json();
      alert(data.detail || '无法预览文件');
      return;
    }
    const data = await resp.json();
    document.getElementById('filePreviewName').textContent = data.name + ' (' + formatSize(data.size) + ')';
    const previewEl = document.getElementById('filePreviewContent');
    previewEl.className = 'file-preview-content';
    const lowerName = data.name.toLowerCase();
    const isMarkdown = lowerName.endsWith('.md') || lowerName.endsWith('.markdown');
    if (isMarkdown && typeof marked !== 'undefined') {
      previewEl.classList.add('msg-ai');
      previewEl.innerHTML = marked.parse(data.content);
    } else {
      previewEl.textContent = data.content;
    }
    document.getElementById('fileList').style.display = 'none';
    document.getElementById('fileBreadcrumb').style.display = 'none';
    document.getElementById('filePreview').classList.add('active');
  } catch (e) {
    console.error('Failed to preview file:', e);
  }
}

function closeFilePreview() {
  document.getElementById('filePreview').classList.remove('active');
  document.getElementById('fileList').style.display = '';
  document.getElementById('fileBreadcrumb').style.display = '';
}