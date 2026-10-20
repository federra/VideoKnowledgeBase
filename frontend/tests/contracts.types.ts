/** Compile-time safeguards; these generated types do not enable business requests. */
import type { components, operations } from '../src/api/generated/first-chain';
import type { ApiClient } from '../src/api/client';
import type { paths as RuntimePaths } from '../src/api/generated/runtime';

type Expect<T extends true> = T;
type Not<T extends boolean> = T extends true ? false : true;
type Existing = Extract<components['schemas']['IntakeCreate']['target'], { kind: 'existing' }>;
type Intake = operations['submitIntelligence']['requestBody']['content']['application/json'];
type Freeze = operations['freezePrediction']['requestBody']['content']['application/json'];
type SourceRequest = operations['createSource']['requestBody']['content']['application/json'];

export type ContractAssertions = [
  Expect<'/api/v1/intelligence/feed' extends keyof RuntimePaths ? true : false>,
  Expect<Not<'lock_version' extends keyof components['schemas']['Snapshot'] ? true : false>>,
  Expect<Not<'updated_at' extends keyof components['schemas']['SnapshotEntry'] ? true : false>>,
  Expect<Awaited<ReturnType<ApiClient['intelligenceFeed']>>['metrics']['likes'] extends string|null ? true : false>,
  Expect<Parameters<ApiClient['uploadFile']>[0] extends Blob ? true : false>,
  Expect<Parameters<ApiClient['uploadFile']>[1]['expected_work_lock_version'] extends string ? true : false>,
  Expect<Not<'org_id' extends keyof Parameters<ApiClient['uploadFile']>[1] ? true : false>>,
  Expect<Awaited<ReturnType<ApiClient['downloadFile']>> extends Blob ? true : false>,
  Expect<Awaited<ReturnType<ApiClient['getSession']>>['authz_version'] extends string ? true : false>,
  Expect<'getTask' extends keyof ApiClient ? true : false>,
  Expect<Existing['expected_lock_version'] extends string ? true : false>,
  Expect<Not<number extends components['schemas']['Observation']['view_count'] ? true : false>>,
  Expect<null extends components['schemas']['Observation']['view_count'] ? true : false>,
  Expect<Not<'org_id' extends keyof Intake ? true : false>>,
  Expect<Not<'frozen_at' extends keyof Freeze ? true : false>>,
  Expect<Not<'reviewer_member_id' extends keyof components['schemas']['HumanDecisionCreate'] ? true : false>>,
  Expect<Not<'actor_member_id' extends keyof components['schemas']['PublishCreate'] ? true : false>>,
  Expect<Not<'inputs' extends keyof components['schemas']['Task'] ? true : false>>,
  Expect<Not<'expected_artifact_lock_version' extends keyof components['schemas']['ArtifactVersion'] ? true : false>>,
  Expect<'/api/v1/tasks/{task_id}' extends keyof RuntimePaths ? true : false>,
  Expect<'/api/health' extends keyof RuntimePaths ? true : false>,
  Expect<'/api/v1/session' extends keyof RuntimePaths ? true : false>,
  Expect<'/api/v1/files' extends keyof RuntimePaths ? true : false>,
  Expect<RuntimePaths['/api/v1/files']['post']['parameters']['query']['expected_work_lock_version'] extends string ? true : false>,
  Expect<RuntimePaths['/api/v1/files/{file_id}/content']['get']['responses'][200]['content']['application/octet-stream'] extends string ? true : false>,
  Expect<{ name: string; business_code: 'motion_comic'; address: string } extends SourceRequest ? true : false>,
];
