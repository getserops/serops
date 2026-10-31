// Fields of a stored batch log (`log._source`). The batch task stores the
// service it parsed as `service`; `service_name` is there only when the
// shipper wrote it, so logs from Pino, ECS or OpenTelemetry showed "—".

export const serviceOf = (source = {}) => {
  const service = source.service_name || source.service;
  if (service && typeof service === 'object') return service.name || null;
  return service || null;
};

export const projectOf = (source = {}) => source.project_name || source.project || null;
