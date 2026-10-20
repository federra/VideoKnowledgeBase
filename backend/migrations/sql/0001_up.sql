CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE organizations (
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	id UUID NOT NULL, 
	name TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	authz_version BIGINT DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_organizations PRIMARY KEY (id), 
	CONSTRAINT ck_organizations_0 CHECK (btrim(name)<>''), 
	CONSTRAINT ck_organizations_1 CHECK (authz_version>0), 
	CONSTRAINT ck_organizations_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_organizations_name_nonempty CHECK (btrim(name)<>'')
)

;

CREATE TABLE business_lines (
	code TEXT NOT NULL, 
	name TEXT NOT NULL, 
	CONSTRAINT pk_business_lines PRIMARY KEY (code), 
	CONSTRAINT ck_business_lines_0 CHECK (code IN ('motion_comic','story_short','ecommerce_video')), 
	CONSTRAINT ck_business_lines_1 CHECK (btrim(name)<>''), 
	CONSTRAINT ck_business_lines_code_nonempty CHECK (btrim(code)<>''), 
	CONSTRAINT ck_business_lines_name_nonempty CHECK (btrim(name)<>'')
)

;

CREATE TABLE platforms (
	code TEXT NOT NULL, 
	name TEXT NOT NULL, 
	CONSTRAINT pk_platforms PRIMARY KEY (code), 
	CONSTRAINT ck_platforms_0 CHECK (btrim(name)<>''), 
	CONSTRAINT ck_platforms_code_nonempty CHECK (btrim(code)<>''), 
	CONSTRAINT ck_platforms_name_nonempty CHECK (btrim(name)<>'')
)

;

CREATE TABLE members (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	login_name TEXT NOT NULL, 
	display_name TEXT NOT NULL, 
	password_hash TEXT, 
	disabled_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_members PRIMARY KEY (id), 
	CONSTRAINT uq_members_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_members_0 CHECK (btrim(login_name)<>''), 
	CONSTRAINT ck_members_1 CHECK (btrim(display_name)<>''), 
	CONSTRAINT ck_members_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_members_login_name_nonempty CHECK (btrim(login_name)<>''), 
	CONSTRAINT ck_members_display_name_nonempty CHECK (btrim(display_name)<>'')
)

;
CREATE INDEX ix_members_fk_0 ON members (org_id);
CREATE UNIQUE INDEX uq_members_login ON members (org_id, lower(login_name));

CREATE TABLE role_definitions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	code TEXT NOT NULL, 
	name TEXT NOT NULL, 
	description TEXT, 
	CONSTRAINT pk_role_definitions PRIMARY KEY (id), 
	CONSTRAINT uq_role_definitions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_role_definitions_0 UNIQUE (org_id, code), 
	CONSTRAINT ck_role_definitions_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_role_definitions_code_nonempty CHECK (btrim(code)<>''), 
	CONSTRAINT ck_role_definitions_name_nonempty CHECK (btrim(name)<>'')
)

;
CREATE INDEX ix_role_definitions_fk_0 ON role_definitions (org_id);

CREATE TABLE role_actions (
	org_id UUID NOT NULL, 
	role_id UUID NOT NULL, 
	action_code TEXT NOT NULL, 
	CONSTRAINT pk_role_actions PRIMARY KEY (org_id, role_id, action_code), 
	CONSTRAINT ck_role_actions_0 CHECK (action_code IN ('content.read','evidence.read','file.read','content.export','content.write','research.submit','research.run','knowledge.candidate.read','knowledge.edit','knowledge.review.run','report.review.run','knowledge.review','knowledge.publish','report.review','evaluation.review','prediction.edit','prediction.freeze','prediction.retract','standard.read','standard.edit','standard.approve','standard.activate','source.configure','collection.run','model.configure','task.read','task.manage','member.manage','role.manage','grant.manage','audit.read')), 
	CONSTRAINT ck_role_actions_action_code_nonempty CHECK (btrim(action_code)<>'')
)

;
CREATE INDEX ix_role_actions_fk_0 ON role_actions (org_id);
CREATE INDEX ix_role_actions_fk_1 ON role_actions (org_id, role_id);

CREATE TABLE grants (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	member_id UUID NOT NULL, 
	role_id UUID NOT NULL, 
	scope_kind TEXT NOT NULL, 
	business_code TEXT, 
	source_id UUID, 
	raw_asset_id UUID, 
	work_id UUID, 
	knowledge_id UUID, 
	standard_id UUID, 
	file_id UUID, 
	task_id UUID, 
	granted_by UUID NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_grants PRIMARY KEY (id), 
	CONSTRAINT uq_grants_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_grants_0 CHECK ((scope_kind='org' AND num_nonnulls(business_code,source_id,raw_asset_id,work_id,knowledge_id,standard_id,file_id,task_id)=0) OR (num_nonnulls(business_code,source_id,raw_asset_id,work_id,knowledge_id,standard_id,file_id,task_id)=1 AND ((scope_kind='business' AND business_code IS NOT NULL) OR (scope_kind='source' AND source_id IS NOT NULL) OR (scope_kind='raw_asset' AND raw_asset_id IS NOT NULL) OR (scope_kind='work' AND work_id IS NOT NULL) OR (scope_kind='knowledge' AND knowledge_id IS NOT NULL) OR (scope_kind='standard' AND standard_id IS NOT NULL) OR (scope_kind='file' AND file_id IS NOT NULL) OR (scope_kind='task' AND task_id IS NOT NULL)))), 
	CONSTRAINT ck_grants_1 CHECK (expires_at IS NULL OR expires_at>created_at), 
	CONSTRAINT ck_grants_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_grants_scope_kind_nonempty CHECK (btrim(scope_kind)<>'')
)

;
CREATE INDEX ix_grants_fk_0 ON grants (org_id);
CREATE INDEX ix_grants_fk_1 ON grants (org_id, member_id);
CREATE INDEX ix_grants_fk_10 ON grants (org_id, task_id);
CREATE INDEX ix_grants_fk_11 ON grants (org_id, granted_by);
CREATE INDEX ix_grants_fk_2 ON grants (org_id, role_id);
CREATE INDEX ix_grants_fk_3 ON grants (business_code);
CREATE INDEX ix_grants_fk_4 ON grants (org_id, source_id);
CREATE INDEX ix_grants_fk_5 ON grants (org_id, raw_asset_id);
CREATE INDEX ix_grants_fk_6 ON grants (org_id, work_id);
CREATE INDEX ix_grants_fk_7 ON grants (org_id, knowledge_id);
CREATE INDEX ix_grants_fk_8 ON grants (org_id, standard_id);
CREATE INDEX ix_grants_fk_9 ON grants (org_id, file_id);
CREATE INDEX ix_grants_org_id_member_id_revoked_at ON grants (org_id, member_id, revoked_at);

CREATE TABLE audit_events (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	actor_member_id UUID, 
	action_code TEXT NOT NULL, 
	target_kind TEXT NOT NULL, 
	target_id UUID, 
	target_version_no INTEGER, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	request_id TEXT NOT NULL, 
	safe_details JSONB DEFAULT '{}' NOT NULL, 
	CONSTRAINT pk_audit_events PRIMARY KEY (id), 
	CONSTRAINT uq_audit_events_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_audit_events_0 CHECK (target_version_no>0), 
	CONSTRAINT ck_audit_events_1 CHECK (btrim(request_id)<>''), 
	CONSTRAINT ck_audit_events_action_code_nonempty CHECK (btrim(action_code)<>''), 
	CONSTRAINT ck_audit_events_target_kind_nonempty CHECK (btrim(target_kind)<>''), 
	CONSTRAINT ck_audit_events_request_id_nonempty CHECK (btrim(request_id)<>''), 
	CONSTRAINT ck_audit_events_safe_details CHECK (jsonb_typeof(safe_details) = 'object')
)

;
CREATE INDEX ix_audit_events_fk_0 ON audit_events (org_id);
CREATE INDEX ix_audit_events_fk_1 ON audit_events (org_id, actor_member_id);
CREATE INDEX ix_audit_events_org_id_occurred_at_id ON audit_events (org_id, occurred_at, id);
CREATE INDEX ix_audit_events_org_id_target_kind_target_id_occurred_at ON audit_events (org_id, target_kind, target_id, occurred_at);

CREATE TABLE file_objects (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	storage_backend TEXT NOT NULL, 
	storage_key TEXT NOT NULL, 
	original_name TEXT, 
	media_type TEXT NOT NULL, 
	byte_size BIGINT NOT NULL, 
	sha256 CHAR(64) NOT NULL, 
	uploaded_by UUID, 
	validation_state TEXT DEFAULT 'pending' NOT NULL, 
	CONSTRAINT pk_file_objects PRIMARY KEY (id), 
	CONSTRAINT uq_file_objects_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_file_objects_0 CHECK (validation_state IN ('pending','accepted','rejected')), 
	CONSTRAINT ck_file_objects_1 CHECK (btrim(media_type)<>''), 
	CONSTRAINT uq_file_objects_0 UNIQUE (org_id, storage_backend, storage_key), 
	CONSTRAINT ck_file_objects_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_file_objects_storage_backend_nonempty CHECK (btrim(storage_backend)<>''), 
	CONSTRAINT ck_file_objects_storage_key_nonempty CHECK (btrim(storage_key)<>''), 
	CONSTRAINT ck_file_objects_media_type_nonempty CHECK (btrim(media_type)<>''), 
	CONSTRAINT ck_file_objects_byte_size CHECK (byte_size >= 0), 
	CONSTRAINT ck_file_objects_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_file_objects_validation_state_nonempty CHECK (btrim(validation_state)<>'')
)

;
CREATE INDEX ix_file_objects_fk_0 ON file_objects (org_id);
CREATE INDEX ix_file_objects_fk_1 ON file_objects (org_id, uploaded_by);
CREATE INDEX ix_file_objects_org_id_sha256 ON file_objects (org_id, sha256);

CREATE TABLE provider_connections (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	provider_code TEXT NOT NULL, 
	name TEXT NOT NULL, 
	secret_ref TEXT NOT NULL, 
	enabled BOOLEAN DEFAULT false NOT NULL, 
	CONSTRAINT pk_provider_connections PRIMARY KEY (id), 
	CONSTRAINT uq_provider_connections_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_provider_connections_0 CHECK (btrim(name)<>''), 
	CONSTRAINT ck_provider_connections_1 CHECK (secret_ref ~ '^[A-Z][A-Z0-9_]*$'), 
	CONSTRAINT uq_provider_connections_0 UNIQUE (org_id, name), 
	CONSTRAINT ck_provider_connections_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_provider_connections_provider_code_nonempty CHECK (btrim(provider_code)<>''), 
	CONSTRAINT ck_provider_connections_name_nonempty CHECK (btrim(name)<>''), 
	CONSTRAINT ck_provider_connections_secret_ref_nonempty CHECK (btrim(secret_ref)<>'')
)

;
CREATE INDEX ix_provider_connections_fk_0 ON provider_connections (org_id);

CREATE TABLE standards (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	code TEXT NOT NULL, 
	kind TEXT NOT NULL, 
	business_code TEXT NOT NULL, 
	name TEXT NOT NULL, 
	active_revision_id UUID, 
	CONSTRAINT pk_standards PRIMARY KEY (id), 
	CONSTRAINT uq_standards_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_standards_0 CHECK (kind IN ('rubric','analysis_template','prompt','parsing_template')), 
	CONSTRAINT uq_standards_0 UNIQUE (org_id, code), 
	CONSTRAINT ck_standards_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_standards_code_nonempty CHECK (btrim(code)<>''), 
	CONSTRAINT ck_standards_kind_nonempty CHECK (btrim(kind)<>''), 
	CONSTRAINT ck_standards_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_standards_name_nonempty CHECK (btrim(name)<>'')
)

;
CREATE INDEX ix_standards_fk_0 ON standards (org_id);
CREATE INDEX ix_standards_fk_1 ON standards (business_code);
CREATE INDEX ix_standards_fk_2 ON standards (org_id, active_revision_id, id);

CREATE TABLE standard_revisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	standard_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	schema_version INTEGER DEFAULT 1 NOT NULL, 
	material_kind TEXT, 
	definition JSONB NOT NULL, 
	origin_kind TEXT NOT NULL, 
	provenance_note TEXT NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_standard_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_standard_revisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_standard_revisions_0 CHECK (material_kind IN ('topic','script','storyboard_script','storyboard_image','asset','finished_video','reference')), 
	CONSTRAINT ck_standard_revisions_1 CHECK (origin_kind IN ('expert_baseline','manual_configuration','learning_candidate')), 
	CONSTRAINT ck_standard_revisions_2 CHECK (btrim(provenance_note)<>''), 
	CONSTRAINT uq_standard_revisions_0 UNIQUE (org_id, standard_id, version_no), 
	CONSTRAINT uq_standard_revisions_1 UNIQUE (org_id, id, standard_id), 
	CONSTRAINT ck_standard_revisions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_standard_revisions_schema_version CHECK (schema_version > 0), 
	CONSTRAINT ck_standard_revisions_definition CHECK (jsonb_typeof(definition) = 'object'), 
	CONSTRAINT ck_standard_revisions_origin_kind_nonempty CHECK (btrim(origin_kind)<>''), 
	CONSTRAINT ck_standard_revisions_provenance_note_nonempty CHECK (btrim(provenance_note)<>''), 
	CONSTRAINT ck_standard_revisions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_standard_revisions_fk_0 ON standard_revisions (org_id);
CREATE INDEX ix_standard_revisions_fk_1 ON standard_revisions (org_id, standard_id);
CREATE INDEX ix_standard_revisions_fk_2 ON standard_revisions (org_id, created_by);

CREATE TABLE ai_config_revisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	config_key TEXT NOT NULL, 
	version_no INTEGER NOT NULL, 
	task_kind TEXT NOT NULL, 
	provider_connection_id UUID NOT NULL, 
	model_identifier TEXT NOT NULL, 
	prompt_revision_id UUID, 
	parameters JSONB DEFAULT '{}' NOT NULL, 
	output_schema JSONB NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_ai_config_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_ai_config_revisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_ai_config_revisions_0 CHECK (btrim(model_identifier)<>''), 
	CONSTRAINT uq_ai_config_revisions_0 UNIQUE (org_id, config_key, version_no), 
	CONSTRAINT ck_ai_config_revisions_config_key_nonempty CHECK (btrim(config_key)<>''), 
	CONSTRAINT ck_ai_config_revisions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_ai_config_revisions_task_kind_nonempty CHECK (btrim(task_kind)<>''), 
	CONSTRAINT ck_ai_config_revisions_model_identifier_nonempty CHECK (btrim(model_identifier)<>''), 
	CONSTRAINT ck_ai_config_revisions_parameters CHECK (jsonb_typeof(parameters) = 'object'), 
	CONSTRAINT ck_ai_config_revisions_output_schema CHECK (jsonb_typeof(output_schema) = 'object'), 
	CONSTRAINT ck_ai_config_revisions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_ai_config_revisions_fk_0 ON ai_config_revisions (org_id);
CREATE INDEX ix_ai_config_revisions_fk_1 ON ai_config_revisions (org_id, provider_connection_id);
CREATE INDEX ix_ai_config_revisions_fk_2 ON ai_config_revisions (org_id, prompt_revision_id);
CREATE INDEX ix_ai_config_revisions_fk_3 ON ai_config_revisions (org_id, created_by);

CREATE TABLE tasks (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	kind TEXT NOT NULL, 
	handler_version TEXT NOT NULL, 
	business_code TEXT, 
	source_id UUID, 
	raw_asset_id UUID, 
	work_id UUID, 
	knowledge_id UUID, 
	standard_id UUID, 
	file_id UUID, 
	requested_by UUID, 
	execution_authorized_by UUID, 
	inputs_sealed_at TIMESTAMP WITH TIME ZONE, 
	outputs_sealed_at TIMESTAMP WITH TIME ZONE, 
	inputs_frozen_at TIMESTAMP WITH TIME ZONE, 
	business_outcome TEXT, 
	max_attempts INTEGER DEFAULT 1 NOT NULL, 
	max_external_calls INTEGER DEFAULT 0 NOT NULL, 
	state TEXT DEFAULT 'queued' NOT NULL, 
	idempotency_key TEXT NOT NULL, 
	input_sha256 CHAR(64) NOT NULL, 
	normalization_version INTEGER DEFAULT 1 NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	cancel_requested_at TIMESTAMP WITH TIME ZONE, 
	safe_error_code TEXT, 
	CONSTRAINT pk_tasks PRIMARY KEY (id), 
	CONSTRAINT uq_tasks_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_tasks_0 CHECK (state IN ('queued','running','succeeded','failed','cancel_requested','cancelled')), 
	CONSTRAINT ck_tasks_1 CHECK (business_outcome IN ('completed','insufficient_evidence')), 
	CONSTRAINT ck_tasks_2 CHECK (num_nonnulls(source_id,raw_asset_id,work_id,knowledge_id,standard_id,file_id)>0), 
	CONSTRAINT ck_tasks_3 CHECK (max_attempts>0 AND max_external_calls>=0), 
	CONSTRAINT ck_tasks_4 CHECK ((state='succeeded')=(business_outcome IS NOT NULL)), 
	CONSTRAINT ck_tasks_5 CHECK ((state IN ('succeeded','failed','cancelled'))=(finished_at IS NOT NULL)), 
	CONSTRAINT ck_tasks_6 CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at>=started_at), 
	CONSTRAINT ck_tasks_7 CHECK (btrim(kind)<>'' AND btrim(handler_version)<>'' AND btrim(idempotency_key)<>''), 
	CONSTRAINT uq_tasks_0 UNIQUE (org_id, kind, idempotency_key), 
	CONSTRAINT ck_tasks_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_tasks_kind_nonempty CHECK (btrim(kind)<>''), 
	CONSTRAINT ck_tasks_handler_version_nonempty CHECK (btrim(handler_version)<>''), 
	CONSTRAINT ck_tasks_state_nonempty CHECK (btrim(state)<>''), 
	CONSTRAINT ck_tasks_idempotency_key_nonempty CHECK (btrim(idempotency_key)<>''), 
	CONSTRAINT ck_tasks_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_tasks_normalization_version CHECK (normalization_version = 1)
)

;
CREATE INDEX ix_tasks_fk_0 ON tasks (org_id);
CREATE INDEX ix_tasks_fk_1 ON tasks (business_code);
CREATE INDEX ix_tasks_fk_2 ON tasks (org_id, source_id);
CREATE INDEX ix_tasks_fk_3 ON tasks (org_id, raw_asset_id);
CREATE INDEX ix_tasks_fk_4 ON tasks (org_id, work_id);
CREATE INDEX ix_tasks_fk_5 ON tasks (org_id, knowledge_id);
CREATE INDEX ix_tasks_fk_6 ON tasks (org_id, standard_id);
CREATE INDEX ix_tasks_fk_7 ON tasks (org_id, file_id);
CREATE INDEX ix_tasks_fk_8 ON tasks (org_id, requested_by);
CREATE INDEX ix_tasks_fk_9 ON tasks (org_id, execution_authorized_by);
CREATE INDEX ix_tasks_org_id_state_created_at_id ON tasks (org_id, state, created_at, id);
CREATE INDEX ix_tasks_state_available_at ON tasks (state, available_at);

CREATE TABLE task_inputs (
	org_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	role TEXT NOT NULL, 
	raw_asset_id UUID, 
	artifact_version_id UUID, 
	input_set_id UUID, 
	snapshot_id UUID, 
	feedback_id UUID, 
	knowledge_revision_id UUID, 
	standard_revision_id UUID, 
	ai_config_revision_id UUID, 
	review_request_id UUID, 
	CONSTRAINT pk_task_inputs PRIMARY KEY (org_id, task_id, position), 
	CONSTRAINT ck_task_inputs_0 CHECK (position>=0), 
	CONSTRAINT ck_task_inputs_1 CHECK (btrim(role)<>''), 
	CONSTRAINT ck_task_inputs_2 CHECK (num_nonnulls(raw_asset_id,artifact_version_id,input_set_id,snapshot_id,feedback_id,knowledge_revision_id,standard_revision_id,ai_config_revision_id,review_request_id)=1), 
	CONSTRAINT ck_task_inputs_role_nonempty CHECK (btrim(role)<>'')
)

;
CREATE INDEX ix_task_inputs_fk_0 ON task_inputs (org_id);
CREATE INDEX ix_task_inputs_fk_1 ON task_inputs (org_id, task_id);
CREATE INDEX ix_task_inputs_fk_10 ON task_inputs (org_id, review_request_id);
CREATE INDEX ix_task_inputs_fk_2 ON task_inputs (org_id, raw_asset_id);
CREATE INDEX ix_task_inputs_fk_3 ON task_inputs (org_id, artifact_version_id);
CREATE INDEX ix_task_inputs_fk_4 ON task_inputs (org_id, input_set_id);
CREATE INDEX ix_task_inputs_fk_5 ON task_inputs (org_id, snapshot_id);
CREATE INDEX ix_task_inputs_fk_6 ON task_inputs (org_id, feedback_id);
CREATE INDEX ix_task_inputs_fk_7 ON task_inputs (org_id, knowledge_revision_id);
CREATE INDEX ix_task_inputs_fk_8 ON task_inputs (org_id, standard_revision_id);
CREATE INDEX ix_task_inputs_fk_9 ON task_inputs (org_id, ai_config_revision_id);

CREATE TABLE task_outputs (
	org_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	role TEXT NOT NULL, 
	raw_asset_id UUID, 
	snapshot_id UUID, 
	feedback_id UUID, 
	report_id UUID, 
	evaluation_id UUID, 
	prediction_id UUID, 
	knowledge_revision_id UUID, 
	ai_execution_id UUID, 
	review_decision_id UUID, 
	artifact_version_id UUID, 
	CONSTRAINT pk_task_outputs PRIMARY KEY (org_id, task_id, position), 
	CONSTRAINT ck_task_outputs_0 CHECK (position>=0), 
	CONSTRAINT ck_task_outputs_1 CHECK (btrim(role)<>''), 
	CONSTRAINT ck_task_outputs_2 CHECK (num_nonnulls(raw_asset_id,snapshot_id,feedback_id,report_id,evaluation_id,prediction_id,knowledge_revision_id,ai_execution_id,review_decision_id,artifact_version_id)=1), 
	CONSTRAINT ck_task_outputs_role_nonempty CHECK (btrim(role)<>'')
)

;
CREATE INDEX ix_task_outputs_fk_0 ON task_outputs (org_id);
CREATE INDEX ix_task_outputs_fk_1 ON task_outputs (org_id, task_id);
CREATE INDEX ix_task_outputs_fk_10 ON task_outputs (org_id, review_decision_id);
CREATE INDEX ix_task_outputs_fk_11 ON task_outputs (org_id, artifact_version_id);
CREATE INDEX ix_task_outputs_fk_2 ON task_outputs (org_id, raw_asset_id);
CREATE INDEX ix_task_outputs_fk_3 ON task_outputs (org_id, snapshot_id);
CREATE INDEX ix_task_outputs_fk_4 ON task_outputs (org_id, feedback_id);
CREATE INDEX ix_task_outputs_fk_5 ON task_outputs (org_id, report_id);
CREATE INDEX ix_task_outputs_fk_6 ON task_outputs (org_id, evaluation_id);
CREATE INDEX ix_task_outputs_fk_7 ON task_outputs (org_id, prediction_id);
CREATE INDEX ix_task_outputs_fk_8 ON task_outputs (org_id, knowledge_revision_id);
CREATE INDEX ix_task_outputs_fk_9 ON task_outputs (org_id, ai_execution_id);

CREATE TABLE task_attempts (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	task_id UUID NOT NULL, 
	attempt_no INTEGER NOT NULL, 
	worker_token UUID NOT NULL, 
	lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	outcome TEXT, 
	safe_error_code TEXT, 
	provider_code TEXT, 
	CONSTRAINT pk_task_attempts PRIMARY KEY (id), 
	CONSTRAINT uq_task_attempts_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_task_attempts_0 CHECK (attempt_no>0), 
	CONSTRAINT ck_task_attempts_1 CHECK (outcome IN ('succeeded','failed','cancelled','lease_lost')), 
	CONSTRAINT ck_task_attempts_2 CHECK ((finished_at IS NULL)=(outcome IS NULL)), 
	CONSTRAINT ck_task_attempts_3 CHECK (finished_at>=started_at), 
	CONSTRAINT ck_task_attempts_4 CHECK (lease_expires_at>started_at), 
	CONSTRAINT uq_task_attempts_0 UNIQUE (org_id, task_id, attempt_no)
)

;
CREATE INDEX ix_task_attempts_fk_0 ON task_attempts (org_id);
CREATE INDEX ix_task_attempts_fk_1 ON task_attempts (org_id, task_id);
CREATE INDEX ix_task_attempts_lease_expires_at ON task_attempts (lease_expires_at) WHERE finished_at IS NULL;
CREATE UNIQUE INDEX ix_task_attempts_org_id_task_id ON task_attempts (org_id, task_id) WHERE finished_at IS NULL;
INSERT INTO business_lines(code,name) VALUES ('motion_comic','AI漫剧'),('story_short','故事短片'),('ecommerce_video','电商短视频');
INSERT INTO platforms(code,name) VALUES ('douyin','抖音');