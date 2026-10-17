// Live demo: disable every write control inside `root` (a Settings page)
// and explain why in a tooltip, instead of letting each Save/Test/Rotate
// fail on click. Read-only controls (tabs, audit-log filters, expanding a
// row) sit inside an element marked data-demo-allowed and stay usable.
// The 403 handler in readOnlyDemo.js stays as the backstop.
const CONTROLS = 'button, input, select, textarea';

export const lockWriteControls = (root, reason) => {
  const apply = () => {
    root.querySelectorAll(CONTROLS).forEach((el) => {
      if (el.closest('[data-demo-allowed]')) return;
      if (!el.disabled) el.disabled = true;
      if (el.title !== reason) el.title = reason;
    });
  };
  apply();
  // React re-renders can re-enable a control (disabled={saving}), so
  // watch for new nodes and for the disabled attribute flipping back.
  const observer = new MutationObserver(apply);
  observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
  return () => observer.disconnect();
};

export default lockWriteControls;
