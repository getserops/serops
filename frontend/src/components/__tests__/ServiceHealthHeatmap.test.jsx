import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k, o) => (o && o.count != null ? `${k}:${o.count}` : k) }) }));

import ServiceHealthHeatmap, { worstFirst } from '../ServiceHealthHeatmap';

const services = [
  { name: 'web', status: 'healthy', health_score: 100, open_issues: 0 },
  { name: 'pricing', status: 'critical', health_score: 20, open_issues: 1 },
  { name: 'catalog', status: 'degraded', health_score: 70, open_issues: 2 },
  { name: 'fleet-redis', status: 'critical', health_score: 20, open_issues: 3 },
];

describe('Service health panel', () => {
  it('sorts the worst service first: lowest health, then most open issues', () => {
    expect(worstFirst(services).map((s) => s.name)).toEqual(['fleet-redis', 'pricing', 'catalog', 'web']);
  });

  it('each tile shows the name, the health and the open issues', () => {
    render(<ServiceHealthHeatmap data={{ services, total_services: 4 }} loading={false} />);
    const tiles = screen.getAllByRole('listitem');
    expect(tiles.map((t) => t.querySelector('.tile-name').textContent)).toEqual(['fleet-redis', 'pricing', 'catalog', 'web']);
    expect(tiles[0].textContent).toContain('20%');
    expect(tiles[0].textContent).toContain('dashboard.openIssues:3');
    expect(tiles[3].textContent).toContain('dashboard.openIssues:0');
  });

  it('tiles carry no inline colour: the status is a class', () => {
    render(<ServiceHealthHeatmap data={{ services, total_services: 4 }} loading={false} />);
    for (const tile of screen.getAllByRole('listitem')) expect(tile.getAttribute('style')).toBeNull();
    expect(screen.getAllByRole('listitem')[0].className).toContain('service-critical');
  });

  it('has no tinted tile background in the stylesheet', () => {
    const css = readFileSync(resolve(__dirname, '../Dashboard.css'), 'utf8');
    expect(css).not.toMatch(/\.service-(healthy|degraded|critical)[^}]*background/);
  });

  it('says so when there is no service', () => {
    render(<ServiceHealthHeatmap data={{ services: [], total_services: 0 }} loading={false} />);
    expect(screen.getByText('dashboard.noServiceData')).toBeTruthy();
  });
});
