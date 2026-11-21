// A reference whose page has nothing to show is not a link: the caller
// renders the same text as plain text when one of these returns null.
//
// The API marks what it cannot open. A span carries `trace_stored: false`
// when no stored trace exists for its trace id, and a commit carries
// `in_batch: false` when its analysis holds no code change with that sha.
// A payload without the flag (an older backend) links as before.

// Where a span's trace opens. `item` is any object holding `trace_id`.
export const tracePath = (item) => {
  if (!item || !item.trace_id || item.trace_stored === false) return null;
  return `/dash/traces/${encodeURIComponent(item.trace_id)}`;
};

// Where a commit opens: the code changes of the analysis it came from.
// `commit` is a sha, or an object holding it as `sha` (a linked commit) or
// as `value` (a correlation entry).
export const commitPath = (batchId, commit) => {
  const sha = commit && typeof commit === 'object' ? (commit.sha || commit.value) : commit;
  if (!batchId || !sha) return null;
  if (commit && typeof commit === 'object' && commit.in_batch === false) return null;
  return `/dash/code-changes/${batchId}?sha=${encodeURIComponent(sha)}`;
};

// How many log lines are shown out of how many the analysis read, when the
// API says some were left out. Null when it does not say, or shows them all.
export const logsTrimmed = (batchData) => {
  const kept = batchData?.logs_kept;
  const total = batchData?.logs_total;
  if (typeof kept !== 'number' || typeof total !== 'number' || kept >= total) return null;
  return { kept, total };
};
