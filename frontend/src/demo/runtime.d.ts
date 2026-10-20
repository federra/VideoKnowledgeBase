import type { DemoRuntime, DemoSnapshot, PageRenderers } from './types';
export function createDemoRuntime(options: {
  onChange: (snapshot: DemoSnapshot) => void;
  renderWorkspace: (module: number, tab: number, renderers: PageRenderers) => string;
}): DemoRuntime;
