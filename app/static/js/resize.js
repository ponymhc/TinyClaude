// ========== Panel Resize ==========
(function initResize() {
  const sidebar = document.getElementById('sidebar');
  const filePanel = document.getElementById('filePanel');
  const sidebarHandle = document.getElementById('sidebarResizeHandle');
  const filePanelHandle = document.getElementById('filePanelResizeHandle');
  function addResize(handle, panel, getMin, getMax, getVar, direction) {
    let startX, startW;
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startX = e.clientX;
      startW = panel.offsetWidth;
      handle.classList.add('active');
      document.body.classList.add('resizing');
      const onMove = (e) => {
        const dx = e.clientX - startX;
        const delta = direction === 'right' ? dx : -dx;
        const newW = Math.max(getMin(), Math.min(getMax(), startW + delta));
        document.documentElement.style.setProperty(getVar(), newW + 'px');
      };
      const onUp = () => {
        handle.classList.remove('active');
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }
  addResize(sidebarHandle, sidebar,
    () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-min')),
    () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-max')),
    () => '--sidebar-width', 'right');
  addResize(filePanelHandle, filePanel,
    () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--file-panel-min')),
    () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--file-panel-max')),
    () => '--file-panel-width', 'left');
})();