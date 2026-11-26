// The Overview's three groups of services (1.5.6), from
// GET /api/data/analytics/service-health/:
//   - open: the service has an open critical or warning issue;
//   - affected: no open issue of its own, but an open issue elsewhere names
//     it among the services it affects (`affected_by`, absent on a server
//     before 1.5.6: treated as empty);
//   - healthy: the rest.
// The server may list fewer services than `total_services` (before 1.5.6 it
// sends 12): the ones it does not list are counted as healthy, since the
// list is sent worst first.

// Two projects may each have a service of the same name: such a name is
// shown with its project, "notifier · Fleet" (`project_name`, sent by the
// server from 1.5.6; without it the name shows alone).
export function withLabels(services) {
  const seen = {};
  for (const s of services) {
    const k = String(s.name).toLowerCase();
    seen[k] = (seen[k] || 0) + 1;
  }
  return services.map((s) => ({
    ...s,
    label: seen[String(s.name).toLowerCase()] > 1 && s.project_name ? `${s.name} · ${s.project_name}` : s.name,
  }));
}

const byName = (a, b) => String(a.label).localeCompare(String(b.label));

export function serviceGroups(data) {
  const services = withLabels(Array.isArray(data?.services) ? data.services : []);
  const total = Math.max(Number(data?.total_services) || 0, services.length);
  const open = [];
  const affected = [];
  const healthy = [];
  for (const s of services) {
    const issues = (s.critical_issues || 0) + (s.warning_issues || 0);
    if (issues > 0) open.push(s);
    else if (Array.isArray(s.affected_by) && s.affected_by.length > 0) affected.push(s);
    else healthy.push(s);
  }
  // Worst first: the most critical issues, then the most issues, then the name.
  open.sort((a, b) => (b.critical_issues || 0) - (a.critical_issues || 0)
    || (b.warning_issues || 0) - (a.warning_issues || 0) || byName(a, b));
  affected.sort(byName);
  healthy.sort(byName);
  return {
    total,
    open,
    affected,
    healthy,
    // Healthy services the server did not list.
    unlisted: total - services.length,
    healthyCount: healthy.length + (total - services.length),
    critical: open.filter((s) => (s.critical_issues || 0) > 0).length,
  };
}
