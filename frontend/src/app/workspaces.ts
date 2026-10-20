import { intelligence } from '../modules/intelligence';
import { research } from '../modules/research';
import { knowledge } from '../modules/knowledge';
import { consoleWorkspace } from '../modules/console';
import type { PageRenderers } from '../demo/types';

export const workspaces = [intelligence, research, knowledge, consoleWorkspace] as const;
export const businesses = ['AI漫剧', '故事短片', '电商短视频'] as const;
export const getWorkspace = (id: number) => workspaces.find(workspace => workspace.id === id);
export function renderWorkspace(module: number, tab: number, renderers: PageRenderers): string {
  if (module === 1 && (tab === 0 || tab === 2)) return "";
  if (module === 0 && tab === 0) return "";
  if (module === 2 && tab === 0) return "";
  if (module === 3 && (tab === 0 || tab === 4)) return "";
  const page = getWorkspace(module)?.pages[tab];
  if (!page) throw new Error('Unknown workspace');
  return page.render(renderers);
}
