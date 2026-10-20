import type { WorkspaceDefinition } from '../../demo/types';
export const knowledge: WorkspaceDefinition = {
  id: 1, name: '藏经阁', icon: 'book',
  pages: [
    { name: '知识浏览', render: pages => pages.knowledgePage() },
    { name: '入库处理', render: pages => pages.intake() },
    { name: '审核队列', render: pages => pages.knowledgePage() },
    { name: '回收站', render: pages => pages.knowledgePage() },
  ],
};
