import type { WorkspaceDefinition } from '../../demo/types';
export const consoleWorkspace: WorkspaceDefinition = {
  id: 3, name: '控制台', icon: 'settings',
  pages: ['采集配置', '处理配置', '评价标准', '权限管理', '运行状态', '模型配置'].map(name => ({
    name, render: pages => pages.consolePage(),
  })),
};
