export interface DemoSnapshot {
  module: number;
  tab: number;
  business: string;
  theme: 'light' | 'dark';
  workTitle: string;
  workId: string;
  sparkCount: number;
}
export interface PageRenderers {
  topicPage: () => string;
  knowledgePage: () => string;
  intake: () => string;
  researchPage: () => string;
  publicationPage: () => string;
  validationPage: () => string;
  consolePage: () => string;
}
export interface DemoRuntime {
  action: (action: string, id?: string) => Promise<void>;
  restoreRoute: () => void;
  dispose: () => void;
}
export interface WorkspaceDefinition {
  id: number;
  name: string;
  icon: string;
  pages: readonly { name: string; render: (renderers: PageRenderers) => string }[];
}
