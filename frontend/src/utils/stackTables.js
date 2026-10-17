// On phones, rows of a .table-stack table render as cards and each cell
// shows its column name from data-label (see primitives.css). This fills
// data-label from the table header, so a table only needs the class.
// Labels written in JSX win; filled ones are refreshed if the header
// changes (language switch). Rows whose cell count doesn't match the
// header (empty states, colSpan) are left alone.
const AUTO = 'data-label-auto';

const labelTable = (table) => {
  const headRow = table.querySelector(':scope > thead > tr');
  const heads = headRow ? [...headRow.children].map((th) => th.textContent.trim()) : [];
  if (!heads.length) return;
  table.querySelectorAll(':scope > tbody > tr').forEach((row) => {
    const cells = [...row.children];
    if (cells.length !== heads.length) return;
    cells.forEach((td, i) => {
      if (td.hasAttribute('data-label') && !td.hasAttribute(AUTO)) return;
      if (heads[i]) {
        if (td.getAttribute('data-label') !== heads[i]) td.setAttribute('data-label', heads[i]);
        td.setAttribute(AUTO, '');
      }
    });
  });
};

export const installStackTables = () => {
  if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return;
  let queued = false;
  const run = () => {
    queued = false;
    document.querySelectorAll('table.table-stack').forEach(labelTable);
  };
  new MutationObserver(() => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(run);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
  run();
};

export default installStackTables;
