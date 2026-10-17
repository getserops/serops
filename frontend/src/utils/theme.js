// One place to apply the theme. data-theme drives our tokens;
// data-bs-theme switches Bootstrap 5.3's own components (tables, forms,
// dropdowns, modals, accordions) so they follow it too.
export const resolveTheme = (theme) => {
  if (theme === 'dark' || theme === 'light') return theme;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export const applyTheme = (theme) => {
  const resolved = resolveTheme(theme);
  const root = document.documentElement;
  root.setAttribute('data-theme', resolved);
  root.setAttribute('data-bs-theme', resolved);
  return resolved;
};

// Compact density tightens tables, cards and rows for people who scan a
// lot of data (see primitives.css).
export const applyDensity = (density) => {
  document.documentElement.setAttribute('data-density', density === 'compact' ? 'compact' : 'comfortable');
};

export default applyTheme;
