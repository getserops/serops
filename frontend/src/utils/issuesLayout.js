/**
 * Which layout the Issues list uses for the room its card has.
 *
 * The table has fixed columns and gives Description what is left. Fixed
 * columns of 726 px in a 728 px card left Description 0 px wide. So the
 * list picks, from the widest that fits:
 *   full    every column at its full width;
 *   medium  the same columns, trimmed;
 *   compact Last seen and Occurrences move under the description (their
 *           sort controls move into the Description header);
 *   cards   one card per issue (the phone layout).
 * Description always gets MIN_DESCRIPTION or more. The widths here are the
 * ones in Issues.css (.issues-tier-*); a test keeps the two in step. They
 * are sized for the French labels ("Vu en dernier", "AVERTISSEMENT").
 */
export const MIN_DESCRIPTION = 240;

// Width of the columns shown by default, per layout.
export const TIER_COLUMNS = {
  full: { select: 40, component: 182, lastSeen: 124, count: 112, severity: 136, status: 104, actions: 88 },
  medium: { select: 40, component: 182, lastSeen: 120, count: 108, severity: 128, status: 96, actions: 64 },
  compact: { select: 40, component: 160, lastSeen: 0, count: 0, severity: 128, status: 96, actions: 64 },
};

// Columns a person can switch on under "Columns"; the same width in every layout.
export const OPTIONAL_COLUMNS = { id: 56, type: 120, age: 124, correlations: 170 };

export const fixedWidth = (tier, visible = {}) => {
  const widths = TIER_COLUMNS[tier];
  let total = widths.select + widths.actions;
  for (const key of ["component", "lastSeen", "count", "severity", "status"]) {
    if (visible[key] !== false) total += widths[key];
  }
  for (const [key, width] of Object.entries(OPTIONAL_COLUMNS)) {
    if (visible[key]) total += width;
  }
  return total;
};

export const issuesTier = (cardWidth, visible = {}) => {
  // Not measured yet (first paint, tests): the full table.
  if (cardWidth == null) return "full";
  // Without a Description column there is nothing to protect.
  const need = visible.description === false ? 0 : MIN_DESCRIPTION;
  for (const tier of ["full", "medium", "compact"]) {
    if (cardWidth >= fixedWidth(tier, visible) + need) return tier;
  }
  return "cards";
};
