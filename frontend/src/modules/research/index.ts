import type { WorkspaceDefinition } from '../../demo/types';
export const research: WorkspaceDefinition = {
  id: 2, name: '研判室', icon: 'research',
  pages: [
    { name: '内容研判', render: pages => pages.researchPage() },
    { name: '发布复盘', render: pages => pages.publicationPage() },
    { name: '规律验证', render: pages => pages.validationPage() },
  ],
};
