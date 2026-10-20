import type { WorkspaceDefinition } from '../../demo/types';
export const intelligence: WorkspaceDefinition = {
  id: 0, name: '情报局', icon: 'radar',
  pages: [
    { name: '情报流', render: () => '' },
    { name: '选题卡', render: pages => pages.topicPage() },
    { name: '待生产', render: pages => pages.topicPage() },
  ],
};
