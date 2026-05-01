if (typeof marked !== 'undefined') {
  marked.setOptions({ breaks: true, gfm: true });
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadSessions();
  loadDirectory('');
  setInterval(refreshFiles, 3000);
  const textarea = document.getElementById('inputBox');
  textarea.addEventListener('input', () => autoResize(textarea));
});