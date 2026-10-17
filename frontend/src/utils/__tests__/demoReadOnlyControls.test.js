import { describe, it, expect } from 'vitest';
import { lockWriteControls } from '../demoReadOnlyControls';
import { installStackTables } from '../stackTables';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('lockWriteControls', () => {
  it('disables write controls with a reason and leaves allowed areas usable', async () => {
    const root = document.createElement('div');
    root.innerHTML = `
      <button id="save">Save</button><input id="name" />
      <div data-demo-allowed><button id="tab">Logs</button></div>`;
    document.body.appendChild(root);
    const stop = lockWriteControls(root, 'read-only');
    expect(root.querySelector('#save').disabled).toBe(true);
    expect(root.querySelector('#save').title).toBe('read-only');
    expect(root.querySelector('#name').disabled).toBe(true);
    expect(root.querySelector('#tab').disabled).toBe(false);

    // A re-render that re-enables a control, or adds a new one, is caught.
    root.querySelector('#save').disabled = false;
    root.insertAdjacentHTML('beforeend', '<button id="test">Test</button>');
    await flush();
    expect(root.querySelector('#save').disabled).toBe(true);
    expect(root.querySelector('#test').disabled).toBe(true);
    stop();
    root.remove();
  });
});

describe('installStackTables', () => {
  it('labels cells from the header, keeps explicit labels, skips colSpan rows', async () => {
    document.body.innerHTML = `
      <table class="table-stack">
        <thead><tr><th>Name</th><th>Status</th><th></th></tr></thead>
        <tbody>
          <tr><td>api</td><td data-label="State">up</td><td>⋮</td></tr>
          <tr><td colspan="3">Nothing here</td></tr>
        </tbody>
      </table>`;
    installStackTables();
    await new Promise((r) => requestAnimationFrame(r));
    const [name, status, actions] = document.querySelectorAll('tbody tr:first-child td');
    expect(name.getAttribute('data-label')).toBe('Name');
    expect(status.getAttribute('data-label')).toBe('State');
    expect(actions.hasAttribute('data-label')).toBe(false);
    expect(document.querySelector('td[colspan]').hasAttribute('data-label')).toBe(false);
  });
});
