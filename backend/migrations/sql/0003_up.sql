
CREATE TABLE works (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	business_code TEXT NOT NULL, 
	work_number TEXT NOT NULL, 
	name TEXT NOT NULL, 
	genre_tags JSONB DEFAULT '[]' NOT NULL, 
	total_episode_count INTEGER, 
	cover_file_id UUID, 
	cover_url TEXT, 
	created_by UUID NOT NULL, 
	report_generation BIGINT DEFAULT 0 NOT NULL, 
	latest_report_id UUID, 
	CONSTRAINT pk_works PRIMARY KEY (id), 
	CONSTRAINT uq_works_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_works_0 CHECK (btrim(name)<>'' AND btrim(work_number)<>''), 
	CONSTRAINT ck_works_1 CHECK (total_episode_count>0), 
	CONSTRAINT ck_works_2 CHECK (business_code='motion_comic' OR total_episode_count IS NULL), 
	CONSTRAINT ck_works_3 CHECK (report_generation>=0), 
	CONSTRAINT uq_works_0 UNIQUE (org_id, work_number), 
	CONSTRAINT ck_works_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_works_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_works_work_number_nonempty CHECK (btrim(work_number)<>''), 
	CONSTRAINT ck_works_name_nonempty CHECK (btrim(name)<>''), 
	CONSTRAINT ck_works_genre_tags CHECK (jsonb_typeof(genre_tags) = 'array'), 
	CONSTRAINT ck_works_total_episode_count CHECK (total_episode_count >= 0)
)

;
CREATE INDEX ix_works_fk_0 ON works (org_id);
CREATE INDEX ix_works_fk_1 ON works (business_code);
CREATE INDEX ix_works_fk_2 ON works (org_id, cover_file_id);
CREATE INDEX ix_works_fk_3 ON works (org_id, created_by);
CREATE INDEX ix_works_fk_4 ON works (org_id, latest_report_id, id);
CREATE INDEX ix_works_org_id_business_code_created_at_id ON works (org_id, business_code, created_at, id);

CREATE TABLE content_units (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	work_id UUID NOT NULL, 
	unit_kind TEXT NOT NULL, 
	episode_no INTEGER, 
	title TEXT, 
	order_key NUMERIC(20, 6), 
	CONSTRAINT pk_content_units PRIMARY KEY (id), 
	CONSTRAINT uq_content_units_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_content_units_0 CHECK (unit_kind IN ('episode','segment')), 
	CONSTRAINT ck_content_units_1 CHECK (episode_no>0), 
	CONSTRAINT ck_content_units_2 CHECK (unit_kind='episode' OR episode_no IS NULL), 
	CONSTRAINT uq_content_units_0 UNIQUE (org_id, id, work_id), 
	CONSTRAINT ck_content_units_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_content_units_unit_kind_nonempty CHECK (btrim(unit_kind)<>'')
)

;
CREATE INDEX ix_content_units_fk_0 ON content_units (org_id);
CREATE INDEX ix_content_units_fk_1 ON content_units (org_id, work_id);
CREATE UNIQUE INDEX ix_content_units_org_id_work_id_episode_no ON content_units (org_id, work_id, episode_no) WHERE unit_kind='episode' AND episode_no IS NOT NULL;

CREATE TABLE artifacts (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	work_id UUID NOT NULL, 
	primary_unit_id UUID, 
	material_number TEXT NOT NULL, 
	title TEXT, 
	material_kind TEXT NOT NULL, 
	current_version_id UUID, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_artifacts PRIMARY KEY (id), 
	CONSTRAINT uq_artifacts_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_artifacts_0 CHECK (material_kind IN ('topic','script','storyboard_script','storyboard_image','asset','finished_video','reference')), 
	CONSTRAINT uq_artifacts_0 UNIQUE (org_id, material_number), 
	CONSTRAINT uq_artifacts_1 UNIQUE (org_id, id, work_id), 
	CONSTRAINT ck_artifacts_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_artifacts_material_number_nonempty CHECK (btrim(material_number)<>''), 
	CONSTRAINT ck_artifacts_material_kind_nonempty CHECK (btrim(material_kind)<>'')
)

;
CREATE INDEX ix_artifacts_fk_0 ON artifacts (org_id);
CREATE INDEX ix_artifacts_fk_1 ON artifacts (org_id, work_id);
CREATE INDEX ix_artifacts_fk_2 ON artifacts (org_id, created_by);
CREATE INDEX ix_artifacts_fk_3 ON artifacts (org_id, primary_unit_id, work_id);
CREATE INDEX ix_artifacts_fk_4 ON artifacts (org_id, current_version_id, id);

CREATE TABLE artifact_versions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	artifact_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	title TEXT, 
	material_kind TEXT NOT NULL, 
	body_text TEXT, 
	file_id UUID, 
	content_sha256 CHAR(64) NOT NULL, 
	normalization_version INTEGER DEFAULT 1 NOT NULL, 
	created_by UUID NOT NULL, 
	revision_reason TEXT, 
	CONSTRAINT pk_artifact_versions PRIMARY KEY (id), 
	CONSTRAINT uq_artifact_versions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_artifact_versions_0 CHECK (material_kind IN ('topic','script','storyboard_script','storyboard_image','asset','finished_video','reference')), 
	CONSTRAINT ck_artifact_versions_1 CHECK (body_text IS NULL OR btrim(body_text)<>''), 
	CONSTRAINT uq_artifact_versions_0 UNIQUE (org_id, artifact_id, version_no), 
	CONSTRAINT uq_artifact_versions_1 UNIQUE (org_id, artifact_id, content_sha256), 
	CONSTRAINT uq_artifact_versions_2 UNIQUE (org_id, id, artifact_id), 
	CONSTRAINT uq_artifact_versions_3 UNIQUE (org_id, id, work_id), 
	CONSTRAINT ck_artifact_versions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_artifact_versions_material_kind_nonempty CHECK (btrim(material_kind)<>''), 
	CONSTRAINT ck_artifact_versions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_artifact_versions_normalization_version CHECK (normalization_version = 1)
)

;
CREATE INDEX ix_artifact_versions_fk_0 ON artifact_versions (org_id);
CREATE INDEX ix_artifact_versions_fk_1 ON artifact_versions (org_id, work_id);
CREATE INDEX ix_artifact_versions_fk_2 ON artifact_versions (org_id, file_id);
CREATE INDEX ix_artifact_versions_fk_3 ON artifact_versions (org_id, created_by);
CREATE INDEX ix_artifact_versions_fk_4 ON artifact_versions (org_id, artifact_id, work_id);

CREATE TABLE artifact_version_sources (
	org_id UUID NOT NULL, 
	artifact_version_id UUID NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	role TEXT NOT NULL, 
	CONSTRAINT pk_artifact_version_sources PRIMARY KEY (org_id, artifact_version_id, raw_asset_id, role), 
	CONSTRAINT ck_artifact_version_sources_0 CHECK (role IN ('primary','reference','transcript','frame')), 
	CONSTRAINT ck_artifact_version_sources_role_nonempty CHECK (btrim(role)<>'')
)

;
CREATE INDEX ix_artifact_version_sources_fk_0 ON artifact_version_sources (org_id);
CREATE INDEX ix_artifact_version_sources_fk_1 ON artifact_version_sources (org_id, artifact_version_id);
CREATE INDEX ix_artifact_version_sources_fk_2 ON artifact_version_sources (org_id, raw_asset_id);

CREATE TABLE artifact_version_units (
	org_id UUID NOT NULL, 
	artifact_version_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	unit_id UUID NOT NULL, 
	episode_no_at_input INTEGER, 
	unit_title_at_input TEXT, 
	CONSTRAINT pk_artifact_version_units PRIMARY KEY (org_id, artifact_version_id, unit_id), 
	CONSTRAINT ck_artifact_version_units_0 CHECK (episode_no_at_input>0)
)

;
CREATE INDEX ix_artifact_version_units_fk_0 ON artifact_version_units (org_id);
CREATE INDEX ix_artifact_version_units_fk_1 ON artifact_version_units (org_id, work_id);
CREATE INDEX ix_artifact_version_units_fk_2 ON artifact_version_units (org_id, artifact_version_id, work_id);
CREATE INDEX ix_artifact_version_units_fk_3 ON artifact_version_units (org_id, unit_id, work_id);

CREATE TABLE artifact_lineage (
	org_id UUID NOT NULL, 
	from_version_id UUID NOT NULL, 
	to_version_id UUID NOT NULL, 
	relation_kind TEXT NOT NULL, 
	CONSTRAINT pk_artifact_lineage PRIMARY KEY (org_id, from_version_id, to_version_id, relation_kind), 
	CONSTRAINT ck_artifact_lineage_0 CHECK (relation_kind IN ('derived_from','references')), 
	CONSTRAINT ck_artifact_lineage_1 CHECK (from_version_id<>to_version_id), 
	CONSTRAINT ck_artifact_lineage_relation_kind_nonempty CHECK (btrim(relation_kind)<>'')
)

;
CREATE INDEX ix_artifact_lineage_fk_0 ON artifact_lineage (org_id);
CREATE INDEX ix_artifact_lineage_fk_1 ON artifact_lineage (org_id, from_version_id);
CREATE INDEX ix_artifact_lineage_fk_2 ON artifact_lineage (org_id, to_version_id);

CREATE TABLE research_submissions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	work_id UUID NOT NULL, 
	artifact_version_id UUID NOT NULL, 
	origin TEXT NOT NULL, 
	snapshot_entry_id UUID, 
	feedback_id UUID, 
	submitted_by UUID NOT NULL, 
	task_id UUID NOT NULL, 
	client_request_key TEXT NOT NULL, 
	import_key TEXT NOT NULL, 
	input_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_research_submissions PRIMARY KEY (id), 
	CONSTRAINT uq_research_submissions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_research_submissions_0 CHECK (origin IN ('intelligence','upload','link','text')), 
	CONSTRAINT ck_research_submissions_1 CHECK ((origin='intelligence')=(snapshot_entry_id IS NOT NULL)), 
	CONSTRAINT ck_research_submissions_2 CHECK (origin='intelligence' OR feedback_id IS NULL), 
	CONSTRAINT ck_research_submissions_3 CHECK (btrim(client_request_key)<>''), 
	CONSTRAINT uq_research_submissions_0 UNIQUE (org_id, submitted_by, client_request_key), 
	CONSTRAINT ck_research_submissions_origin_nonempty CHECK (btrim(origin)<>''), 
	CONSTRAINT ck_research_submissions_client_request_key_nonempty CHECK (btrim(client_request_key)<>''), 
	CONSTRAINT ck_research_submissions_import_key_nonempty CHECK (btrim(import_key)<>''), 
	CONSTRAINT ck_research_submissions_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_research_submissions_fk_0 ON research_submissions (org_id);
CREATE INDEX ix_research_submissions_fk_1 ON research_submissions (org_id, work_id);
CREATE INDEX ix_research_submissions_fk_2 ON research_submissions (org_id, snapshot_entry_id);
CREATE INDEX ix_research_submissions_fk_3 ON research_submissions (org_id, feedback_id);
CREATE INDEX ix_research_submissions_fk_4 ON research_submissions (org_id, submitted_by);
CREATE INDEX ix_research_submissions_fk_5 ON research_submissions (org_id, task_id);
CREATE INDEX ix_research_submissions_fk_6 ON research_submissions (org_id, artifact_version_id, work_id);
CREATE INDEX ix_research_submissions_org_id_work_id_import_key_created_at_id ON research_submissions (org_id, work_id, import_key, created_at, id);

CREATE TABLE preliminary_assessments (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	submission_id UUID NOT NULL, 
	assessed_by UUID NOT NULL, 
	quality_grade TEXT, 
	opinion TEXT, 
	learning_tags JSONB DEFAULT '[]' NOT NULL, 
	additional_learning TEXT, 
	confirmed_business_code TEXT NOT NULL, 
	confirmed_genre_tags JSONB DEFAULT '[]' NOT NULL, 
	work_name_at_submit TEXT NOT NULL, 
	total_episodes_at_submit INTEGER, 
	episode_no_at_submit INTEGER, 
	CONSTRAINT pk_preliminary_assessments PRIMARY KEY (id), 
	CONSTRAINT uq_preliminary_assessments_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_preliminary_assessments_0 CHECK (quality_grade IN ('S','A','B','C')), 
	CONSTRAINT ck_preliminary_assessments_1 CHECK (total_episodes_at_submit>0 AND episode_no_at_submit>0), 
	CONSTRAINT ck_preliminary_assessments_2 CHECK (episode_no_at_submit<=total_episodes_at_submit), 
	CONSTRAINT ck_preliminary_assessments_3 CHECK (btrim(work_name_at_submit)<>''), 
	CONSTRAINT uq_preliminary_assessments_0 UNIQUE (org_id, submission_id), 
	CONSTRAINT ck_preliminary_assessments_learning_tags CHECK (jsonb_typeof(learning_tags) = 'array'), 
	CONSTRAINT ck_preliminary_assessments_confirmed_business_code_nonempty CHECK (btrim(confirmed_business_code)<>''), 
	CONSTRAINT ck_preliminary_assessments_confirmed_genre_tags CHECK (jsonb_typeof(confirmed_genre_tags) = 'array'), 
	CONSTRAINT ck_preliminary_assessments_work_name_at_submit_nonempty CHECK (btrim(work_name_at_submit)<>'')
)

;
CREATE INDEX ix_preliminary_assessments_fk_0 ON preliminary_assessments (org_id);
CREATE INDEX ix_preliminary_assessments_fk_1 ON preliminary_assessments (org_id, submission_id);
CREATE INDEX ix_preliminary_assessments_fk_2 ON preliminary_assessments (org_id, assessed_by);
CREATE INDEX ix_preliminary_assessments_fk_3 ON preliminary_assessments (confirmed_business_code);

CREATE TABLE input_sets (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	work_id UUID NOT NULL, 
	scope TEXT NOT NULL, 
	unit_id UUID, 
	artifact_id UUID, 
	business_code TEXT NOT NULL, 
	manifest_sha256 CHAR(64) NOT NULL, 
	normalization_version INTEGER DEFAULT 1 NOT NULL, 
	total_episode_count_at_input INTEGER, 
	CONSTRAINT pk_input_sets PRIMARY KEY (id), 
	CONSTRAINT uq_input_sets_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_input_sets_0 CHECK (scope IN ('work','unit','artifact')), 
	CONSTRAINT ck_input_sets_1 CHECK (total_episode_count_at_input>0), 
	CONSTRAINT ck_input_sets_2 CHECK ((scope='work' AND num_nonnulls(unit_id,artifact_id)=0) OR (scope='unit' AND unit_id IS NOT NULL AND artifact_id IS NULL) OR (scope='artifact' AND artifact_id IS NOT NULL AND unit_id IS NULL)), 
	CONSTRAINT uq_input_sets_0 UNIQUE (org_id, work_id, manifest_sha256), 
	CONSTRAINT uq_input_sets_1 UNIQUE (org_id, id, work_id), 
	CONSTRAINT ck_input_sets_scope_nonempty CHECK (btrim(scope)<>''), 
	CONSTRAINT ck_input_sets_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_input_sets_manifest_sha256 CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_input_sets_normalization_version CHECK (normalization_version = 1)
)

;
CREATE INDEX ix_input_sets_fk_0 ON input_sets (org_id);
CREATE INDEX ix_input_sets_fk_1 ON input_sets (org_id, work_id);
CREATE INDEX ix_input_sets_fk_2 ON input_sets (business_code);
CREATE INDEX ix_input_sets_fk_3 ON input_sets (org_id, unit_id, work_id);
CREATE INDEX ix_input_sets_fk_4 ON input_sets (org_id, artifact_id, work_id);

CREATE TABLE input_set_items (
	org_id UUID NOT NULL, 
	input_set_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	artifact_version_id UUID NOT NULL, 
	role TEXT NOT NULL, 
	position INTEGER NOT NULL, 
	CONSTRAINT pk_input_set_items PRIMARY KEY (org_id, input_set_id, artifact_version_id, role), 
	CONSTRAINT ck_input_set_items_0 CHECK (role IN ('primary','reference')), 
	CONSTRAINT ck_input_set_items_1 CHECK (position>=0), 
	CONSTRAINT uq_input_set_items_0 UNIQUE (org_id, input_set_id, position), 
	CONSTRAINT ck_input_set_items_role_nonempty CHECK (btrim(role)<>'')
)

;
CREATE INDEX ix_input_set_items_fk_0 ON input_set_items (org_id);
CREATE INDEX ix_input_set_items_fk_1 ON input_set_items (org_id, work_id);
CREATE INDEX ix_input_set_items_fk_2 ON input_set_items (org_id, input_set_id, work_id);
CREATE INDEX ix_input_set_items_fk_3 ON input_set_items (org_id, artifact_version_id, work_id);

CREATE TABLE analysis_runs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	report_generation BIGINT NOT NULL, 
	input_set_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	template_revision_id UUID NOT NULL, 
	rubric_revision_id UUID, 
	ai_config_revision_id UUID NOT NULL, 
	state TEXT DEFAULT 'queued' NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	safe_error_code TEXT, 
	CONSTRAINT pk_analysis_runs PRIMARY KEY (id), 
	CONSTRAINT uq_analysis_runs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_analysis_runs_0 CHECK (report_generation>0), 
	CONSTRAINT ck_analysis_runs_1 CHECK (state IN ('queued','running','succeeded','failed','cancel_requested','cancelled')), 
	CONSTRAINT uq_analysis_runs_0 UNIQUE (org_id, task_id), 
	CONSTRAINT ck_analysis_runs_state_nonempty CHECK (btrim(state)<>'')
)

;
CREATE INDEX ix_analysis_runs_fk_0 ON analysis_runs (org_id);
CREATE INDEX ix_analysis_runs_fk_1 ON analysis_runs (org_id, input_set_id);
CREATE INDEX ix_analysis_runs_fk_2 ON analysis_runs (org_id, task_id);
CREATE INDEX ix_analysis_runs_fk_3 ON analysis_runs (org_id, template_revision_id);
CREATE INDEX ix_analysis_runs_fk_4 ON analysis_runs (org_id, rubric_revision_id);
CREATE INDEX ix_analysis_runs_fk_5 ON analysis_runs (org_id, ai_config_revision_id);
CREATE INDEX ix_analysis_runs_org_id_input_set_id_created_at_id ON analysis_runs (org_id, input_set_id, created_at, id);

CREATE TABLE ai_executions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	config_revision_id UUID NOT NULL, 
	invocation_no INTEGER NOT NULL, 
	input_sha256 CHAR(64) NOT NULL, 
	input_manifest_file_id UUID NOT NULL, 
	provider_request_id TEXT, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	result_state TEXT, 
	output_file_id UUID, 
	safe_error_code TEXT, 
	input_tokens BIGINT, 
	output_tokens BIGINT, 
	cost_amount NUMERIC(20, 6), 
	cost_currency TEXT, 
	CONSTRAINT pk_ai_executions PRIMARY KEY (id), 
	CONSTRAINT uq_ai_executions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_ai_executions_0 CHECK (invocation_no>0), 
	CONSTRAINT ck_ai_executions_1 CHECK (result_state IN ('completed','insufficient_evidence','failed')), 
	CONSTRAINT ck_ai_executions_2 CHECK ((finished_at IS NULL)=(result_state IS NULL)), 
	CONSTRAINT ck_ai_executions_3 CHECK (finished_at>=started_at), 
	CONSTRAINT ck_ai_executions_4 CHECK (result_state IS DISTINCT FROM 'completed' OR output_file_id IS NOT NULL), 
	CONSTRAINT ck_ai_executions_5 CHECK ((cost_amount IS NULL)=(cost_currency IS NULL)), 
	CONSTRAINT ck_ai_executions_6 CHECK (cost_amount>=0), 
	CONSTRAINT uq_ai_executions_0 UNIQUE (org_id, attempt_id, invocation_no), 
	CONSTRAINT ck_ai_executions_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_ai_executions_input_tokens CHECK (input_tokens >= 0), 
	CONSTRAINT ck_ai_executions_output_tokens CHECK (output_tokens >= 0)
)

;
CREATE INDEX ix_ai_executions_fk_0 ON ai_executions (org_id);
CREATE INDEX ix_ai_executions_fk_1 ON ai_executions (org_id, task_id);
CREATE INDEX ix_ai_executions_fk_2 ON ai_executions (org_id, attempt_id);
CREATE INDEX ix_ai_executions_fk_3 ON ai_executions (org_id, config_revision_id);
CREATE INDEX ix_ai_executions_fk_4 ON ai_executions (org_id, input_manifest_file_id);
CREATE INDEX ix_ai_executions_fk_5 ON ai_executions (org_id, output_file_id);

CREATE TABLE analysis_reports (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	work_id UUID NOT NULL, 
	input_set_id UUID NOT NULL, 
	analysis_run_id UUID NOT NULL, 
	ai_execution_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	coverage_kind TEXT NOT NULL, 
	schema_version INTEGER DEFAULT 1 NOT NULL, 
	body JSONB NOT NULL, 
	missing_inputs JSONB DEFAULT '[]' NOT NULL, 
	result_state TEXT NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_analysis_reports PRIMARY KEY (id), 
	CONSTRAINT uq_analysis_reports_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_analysis_reports_0 CHECK (coverage_kind='partial'), 
	CONSTRAINT ck_analysis_reports_1 CHECK (result_state IN ('completed','insufficient_evidence')), 
	CONSTRAINT uq_analysis_reports_0 UNIQUE (org_id, work_id, version_no), 
	CONSTRAINT uq_analysis_reports_1 UNIQUE (org_id, analysis_run_id), 
	CONSTRAINT uq_analysis_reports_2 UNIQUE (org_id, id, work_id), 
	CONSTRAINT ck_analysis_reports_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_analysis_reports_coverage_kind_nonempty CHECK (btrim(coverage_kind)<>''), 
	CONSTRAINT ck_analysis_reports_schema_version CHECK (schema_version > 0), 
	CONSTRAINT ck_analysis_reports_body CHECK (jsonb_typeof(body) = 'object'), 
	CONSTRAINT ck_analysis_reports_missing_inputs CHECK (jsonb_typeof(missing_inputs) = 'array'), 
	CONSTRAINT ck_analysis_reports_result_state_nonempty CHECK (btrim(result_state)<>''), 
	CONSTRAINT ck_analysis_reports_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_analysis_reports_fk_0 ON analysis_reports (org_id);
CREATE INDEX ix_analysis_reports_fk_1 ON analysis_reports (org_id, work_id);
CREATE INDEX ix_analysis_reports_fk_2 ON analysis_reports (org_id, analysis_run_id);
CREATE INDEX ix_analysis_reports_fk_3 ON analysis_reports (org_id, ai_execution_id);
CREATE INDEX ix_analysis_reports_fk_4 ON analysis_reports (org_id, input_set_id, work_id);

CREATE TABLE report_units (
	org_id UUID NOT NULL, 
	report_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	unit_id UUID NOT NULL, 
	coverage_state TEXT NOT NULL, 
	episode_no_at_report INTEGER, 
	unit_title_at_report TEXT, 
	CONSTRAINT pk_report_units PRIMARY KEY (org_id, report_id, unit_id), 
	CONSTRAINT ck_report_units_0 CHECK (coverage_state IN ('analyzed','missing','failed','insufficient_evidence')), 
	CONSTRAINT ck_report_units_1 CHECK (episode_no_at_report>0), 
	CONSTRAINT ck_report_units_coverage_state_nonempty CHECK (btrim(coverage_state)<>'')
)

;
CREATE INDEX ix_report_units_fk_0 ON report_units (org_id);
CREATE INDEX ix_report_units_fk_1 ON report_units (org_id, work_id);
CREATE INDEX ix_report_units_fk_2 ON report_units (org_id, report_id, work_id);
CREATE INDEX ix_report_units_fk_3 ON report_units (org_id, unit_id, work_id);

CREATE TABLE evidence_refs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	raw_asset_id UUID, 
	artifact_version_id UUID, 
	locator_kind TEXT NOT NULL, 
	paragraph_no INTEGER, 
	page_no INTEGER, 
	start_ms BIGINT, 
	end_ms BIGINT, 
	quoted_text TEXT, 
	CONSTRAINT pk_evidence_refs PRIMARY KEY (id), 
	CONSTRAINT uq_evidence_refs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_evidence_refs_0 CHECK (num_nonnulls(raw_asset_id,artifact_version_id)=1), 
	CONSTRAINT ck_evidence_refs_1 CHECK (COALESCE(((locator_kind='whole' AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=0) OR (locator_kind='paragraph' AND paragraph_no>0 AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=1) OR (locator_kind='page' AND page_no>0 AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=1) OR (locator_kind='time' AND start_ms IS NOT NULL AND end_ms IS NOT NULL AND paragraph_no IS NULL AND page_no IS NULL AND start_ms>=0 AND end_ms>=start_ms)),false)), 
	CONSTRAINT ck_evidence_refs_locator_kind_nonempty CHECK (btrim(locator_kind)<>'')
)

;
CREATE INDEX ix_evidence_refs_fk_0 ON evidence_refs (org_id);
CREATE INDEX ix_evidence_refs_fk_1 ON evidence_refs (org_id, raw_asset_id);
CREATE INDEX ix_evidence_refs_fk_2 ON evidence_refs (org_id, artifact_version_id);

CREATE TABLE report_evidence (
	org_id UUID NOT NULL, 
	report_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	claim_path TEXT NOT NULL, 
	CONSTRAINT pk_report_evidence PRIMARY KEY (org_id, report_id, claim_path, evidence_id), 
	CONSTRAINT ck_report_evidence_0 CHECK (btrim(claim_path)<>''), 
	CONSTRAINT ck_report_evidence_claim_path_nonempty CHECK (btrim(claim_path)<>'')
)

;
CREATE INDEX ix_report_evidence_fk_0 ON report_evidence (org_id);
CREATE INDEX ix_report_evidence_fk_1 ON report_evidence (org_id, report_id);
CREATE INDEX ix_report_evidence_fk_2 ON report_evidence (org_id, evidence_id);

CREATE TABLE quality_evaluations (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	input_set_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	rubric_revision_id UUID NOT NULL, 
	ai_execution_id UUID NOT NULL, 
	report_id UUID, 
	result_state TEXT NOT NULL, 
	quality_grade TEXT, 
	schema_version INTEGER DEFAULT 1 NOT NULL, 
	dimensions JSONB NOT NULL, 
	summary TEXT, 
	content_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_quality_evaluations PRIMARY KEY (id), 
	CONSTRAINT uq_quality_evaluations_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_quality_evaluations_0 CHECK (result_state IN ('completed','insufficient_evidence','failed')), 
	CONSTRAINT ck_quality_evaluations_1 CHECK (quality_grade IN ('S','A','B','C')), 
	CONSTRAINT ck_quality_evaluations_2 CHECK (result_state<>'insufficient_evidence' OR quality_grade IS NULL), 
	CONSTRAINT uq_quality_evaluations_0 UNIQUE (org_id, task_id), 
	CONSTRAINT ck_quality_evaluations_result_state_nonempty CHECK (btrim(result_state)<>''), 
	CONSTRAINT ck_quality_evaluations_schema_version CHECK (schema_version > 0), 
	CONSTRAINT ck_quality_evaluations_dimensions CHECK (jsonb_typeof(dimensions) = 'object'), 
	CONSTRAINT ck_quality_evaluations_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_quality_evaluations_fk_0 ON quality_evaluations (org_id);
CREATE INDEX ix_quality_evaluations_fk_1 ON quality_evaluations (org_id, input_set_id);
CREATE INDEX ix_quality_evaluations_fk_2 ON quality_evaluations (org_id, task_id);
CREATE INDEX ix_quality_evaluations_fk_3 ON quality_evaluations (org_id, rubric_revision_id);
CREATE INDEX ix_quality_evaluations_fk_4 ON quality_evaluations (org_id, ai_execution_id);
CREATE INDEX ix_quality_evaluations_fk_5 ON quality_evaluations (org_id, report_id);
CREATE INDEX ix_quality_evaluations_org_id_input_set_id_created_at_id ON quality_evaluations (org_id, input_set_id, created_at, id);

CREATE TABLE evaluation_evidence (
	org_id UUID NOT NULL, 
	evaluation_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	dimension_code TEXT NOT NULL, 
	CONSTRAINT pk_evaluation_evidence PRIMARY KEY (org_id, evaluation_id, dimension_code, evidence_id), 
	CONSTRAINT ck_evaluation_evidence_dimension_code_nonempty CHECK (btrim(dimension_code)<>'')
)

;
CREATE INDEX ix_evaluation_evidence_fk_0 ON evaluation_evidence (org_id);
CREATE INDEX ix_evaluation_evidence_fk_1 ON evaluation_evidence (org_id, evaluation_id);
CREATE INDEX ix_evaluation_evidence_fk_2 ON evaluation_evidence (org_id, evidence_id);

CREATE TABLE metric_specs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	code TEXT NOT NULL, 
	version_no INTEGER NOT NULL, 
	name TEXT NOT NULL, 
	unit TEXT NOT NULL, 
	definition TEXT NOT NULL, 
	aggregation_kind TEXT NOT NULL, 
	denominator_definition TEXT, 
	CONSTRAINT pk_metric_specs PRIMARY KEY (id), 
	CONSTRAINT uq_metric_specs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_metric_specs_0 CHECK (aggregation_kind IN ('cumulative','window_count','rate')), 
	CONSTRAINT ck_metric_specs_1 CHECK (aggregation_kind<>'rate' OR (denominator_definition IS NOT NULL AND btrim(denominator_definition)<>'')), 
	CONSTRAINT uq_metric_specs_0 UNIQUE (org_id, code, version_no), 
	CONSTRAINT ck_metric_specs_code_nonempty CHECK (btrim(code)<>''), 
	CONSTRAINT ck_metric_specs_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_metric_specs_name_nonempty CHECK (btrim(name)<>''), 
	CONSTRAINT ck_metric_specs_unit_nonempty CHECK (btrim(unit)<>''), 
	CONSTRAINT ck_metric_specs_definition_nonempty CHECK (btrim(definition)<>''), 
	CONSTRAINT ck_metric_specs_aggregation_kind_nonempty CHECK (btrim(aggregation_kind)<>'')
)

;
CREATE INDEX ix_metric_specs_fk_0 ON metric_specs (org_id);

CREATE TABLE prediction_drafts (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	input_set_id UUID NOT NULL, 
	metric_spec_id UUID NOT NULL, 
	author_kind TEXT NOT NULL, 
	author_member_id UUID, 
	ai_execution_id UUID, 
	platform_code TEXT NOT NULL, 
	account_id UUID, 
	window_start_offset_seconds BIGINT NOT NULL, 
	window_end_offset_seconds BIGINT NOT NULL, 
	conditions JSONB NOT NULL, 
	context_kind TEXT DEFAULT 'unknown' NOT NULL, 
	outcome_exposure TEXT DEFAULT 'unknown' NOT NULL, 
	lower_bound NUMERIC(20, 6), 
	upper_bound NUMERIC(20, 6), 
	rationale TEXT NOT NULL, 
	uncertainty_note TEXT NOT NULL, 
	rubric_revision_id UUID, 
	prompt_revision_id UUID, 
	supersedes_prediction_id UUID, 
	reliability TEXT NOT NULL, 
	CONSTRAINT pk_prediction_drafts PRIMARY KEY (id), 
	CONSTRAINT uq_prediction_drafts_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_prediction_drafts_0 CHECK (author_kind IN ('human','ai')), 
	CONSTRAINT ck_prediction_drafts_1 CHECK ((author_kind='human' AND author_member_id IS NOT NULL AND ai_execution_id IS NULL) OR (author_kind='ai' AND author_member_id IS NULL AND ai_execution_id IS NOT NULL)), 
	CONSTRAINT ck_prediction_drafts_2 CHECK (window_start_offset_seconds>=0 AND window_end_offset_seconds>window_start_offset_seconds), 
	CONSTRAINT ck_prediction_drafts_3 CHECK ((lower_bound IS NULL)=(upper_bound IS NULL)), 
	CONSTRAINT ck_prediction_drafts_4 CHECK (lower_bound>=0 AND upper_bound>=lower_bound), 
	CONSTRAINT ck_prediction_drafts_5 CHECK (context_kind IN ('prospective_candidate','retrospective','unknown')), 
	CONSTRAINT ck_prediction_drafts_6 CHECK (outcome_exposure IN ('unobserved','observed','unknown')), 
	CONSTRAINT ck_prediction_drafts_7 CHECK (btrim(rationale)<>'' AND btrim(uncertainty_note)<>''), 
	CONSTRAINT ck_prediction_drafts_8 CHECK (reliability IN ('estimable','insufficient_evidence')), 
	CONSTRAINT ck_prediction_drafts_9 CHECK ((reliability='estimable')=(lower_bound IS NOT NULL)), 
	CONSTRAINT ck_prediction_drafts_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_prediction_drafts_author_kind_nonempty CHECK (btrim(author_kind)<>''), 
	CONSTRAINT ck_prediction_drafts_platform_code_nonempty CHECK (btrim(platform_code)<>''), 
	CONSTRAINT ck_prediction_drafts_conditions CHECK (jsonb_typeof(conditions) = 'object'), 
	CONSTRAINT ck_prediction_drafts_context_kind_nonempty CHECK (btrim(context_kind)<>''), 
	CONSTRAINT ck_prediction_drafts_outcome_exposure_nonempty CHECK (btrim(outcome_exposure)<>''), 
	CONSTRAINT ck_prediction_drafts_rationale_nonempty CHECK (btrim(rationale)<>''), 
	CONSTRAINT ck_prediction_drafts_uncertainty_note_nonempty CHECK (btrim(uncertainty_note)<>''), 
	CONSTRAINT ck_prediction_drafts_reliability_nonempty CHECK (btrim(reliability)<>'')
)

;
CREATE INDEX ix_prediction_drafts_fk_0 ON prediction_drafts (org_id);
CREATE INDEX ix_prediction_drafts_fk_1 ON prediction_drafts (org_id, input_set_id);
CREATE INDEX ix_prediction_drafts_fk_2 ON prediction_drafts (org_id, metric_spec_id);
CREATE INDEX ix_prediction_drafts_fk_3 ON prediction_drafts (org_id, author_member_id);
CREATE INDEX ix_prediction_drafts_fk_4 ON prediction_drafts (org_id, ai_execution_id);
CREATE INDEX ix_prediction_drafts_fk_5 ON prediction_drafts (platform_code);
CREATE INDEX ix_prediction_drafts_fk_6 ON prediction_drafts (org_id, account_id);
CREATE INDEX ix_prediction_drafts_fk_7 ON prediction_drafts (org_id, rubric_revision_id);
CREATE INDEX ix_prediction_drafts_fk_8 ON prediction_drafts (org_id, prompt_revision_id);
CREATE INDEX ix_prediction_drafts_fk_9 ON prediction_drafts (org_id, supersedes_prediction_id);

CREATE TABLE predictions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	input_set_id UUID NOT NULL, 
	metric_spec_id UUID NOT NULL, 
	author_kind TEXT NOT NULL, 
	author_member_id UUID, 
	ai_execution_id UUID, 
	platform_code TEXT NOT NULL, 
	account_id UUID, 
	window_start_offset_seconds BIGINT NOT NULL, 
	window_end_offset_seconds BIGINT NOT NULL, 
	conditions JSONB NOT NULL, 
	context_kind TEXT DEFAULT 'unknown' NOT NULL, 
	outcome_exposure TEXT DEFAULT 'unknown' NOT NULL, 
	lower_bound NUMERIC(20, 6), 
	upper_bound NUMERIC(20, 6), 
	rationale TEXT NOT NULL, 
	uncertainty_note TEXT NOT NULL, 
	rubric_revision_id UUID, 
	prompt_revision_id UUID, 
	supersedes_prediction_id UUID, 
	draft_id UUID NOT NULL, 
	draft_lock_version BIGINT NOT NULL, 
	frozen_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	freeze_transaction xid8 DEFAULT pg_current_xact_id() NOT NULL, 
	frozen_by UUID NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_predictions PRIMARY KEY (id), 
	CONSTRAINT uq_predictions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_predictions_0 CHECK (author_kind IN ('human','ai')), 
	CONSTRAINT ck_predictions_1 CHECK ((author_kind='human' AND author_member_id IS NOT NULL AND ai_execution_id IS NULL) OR (author_kind='ai' AND author_member_id IS NULL AND ai_execution_id IS NOT NULL)), 
	CONSTRAINT ck_predictions_2 CHECK (window_start_offset_seconds>=0 AND window_end_offset_seconds>window_start_offset_seconds), 
	CONSTRAINT ck_predictions_3 CHECK ((lower_bound IS NULL)=(upper_bound IS NULL)), 
	CONSTRAINT ck_predictions_4 CHECK (lower_bound>=0 AND upper_bound>=lower_bound), 
	CONSTRAINT ck_predictions_5 CHECK (context_kind IN ('prospective_candidate','retrospective','unknown')), 
	CONSTRAINT ck_predictions_6 CHECK (outcome_exposure IN ('unobserved','observed','unknown')), 
	CONSTRAINT ck_predictions_7 CHECK (btrim(rationale)<>'' AND btrim(uncertainty_note)<>''), 
	CONSTRAINT ck_predictions_8 CHECK (lower_bound IS NOT NULL), 
	CONSTRAINT ck_predictions_9 CHECK (draft_lock_version>0), 
	CONSTRAINT uq_predictions_0 UNIQUE (org_id, draft_id, draft_lock_version), 
	CONSTRAINT ck_predictions_author_kind_nonempty CHECK (btrim(author_kind)<>''), 
	CONSTRAINT ck_predictions_platform_code_nonempty CHECK (btrim(platform_code)<>''), 
	CONSTRAINT ck_predictions_conditions CHECK (jsonb_typeof(conditions) = 'object'), 
	CONSTRAINT ck_predictions_context_kind_nonempty CHECK (btrim(context_kind)<>''), 
	CONSTRAINT ck_predictions_outcome_exposure_nonempty CHECK (btrim(outcome_exposure)<>''), 
	CONSTRAINT ck_predictions_rationale_nonempty CHECK (btrim(rationale)<>''), 
	CONSTRAINT ck_predictions_uncertainty_note_nonempty CHECK (btrim(uncertainty_note)<>''), 
	CONSTRAINT ck_predictions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_predictions_fk_0 ON predictions (org_id);
CREATE INDEX ix_predictions_fk_1 ON predictions (org_id, input_set_id);
CREATE INDEX ix_predictions_fk_10 ON predictions (org_id, draft_id);
CREATE INDEX ix_predictions_fk_11 ON predictions (org_id, frozen_by);
CREATE INDEX ix_predictions_fk_2 ON predictions (org_id, metric_spec_id);
CREATE INDEX ix_predictions_fk_3 ON predictions (org_id, author_member_id);
CREATE INDEX ix_predictions_fk_4 ON predictions (org_id, ai_execution_id);
CREATE INDEX ix_predictions_fk_5 ON predictions (platform_code);
CREATE INDEX ix_predictions_fk_6 ON predictions (org_id, account_id);
CREATE INDEX ix_predictions_fk_7 ON predictions (org_id, rubric_revision_id);
CREATE INDEX ix_predictions_fk_8 ON predictions (org_id, prompt_revision_id);
CREATE INDEX ix_predictions_fk_9 ON predictions (org_id, supersedes_prediction_id);

CREATE TABLE prediction_events (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	prediction_id UUID NOT NULL, 
	event_kind TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	actor_member_id UUID NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	CONSTRAINT pk_prediction_events PRIMARY KEY (id), 
	CONSTRAINT uq_prediction_events_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_prediction_events_0 CHECK (event_kind IN ('freeze_confirmed','retracted')), 
	CONSTRAINT ck_prediction_events_1 CHECK (btrim(reason)<>''), 
	CONSTRAINT uq_prediction_events_0 UNIQUE (org_id, prediction_id, event_kind), 
	CONSTRAINT ck_prediction_events_event_kind_nonempty CHECK (btrim(event_kind)<>''), 
	CONSTRAINT ck_prediction_events_reason_nonempty CHECK (btrim(reason)<>'')
)

;
CREATE INDEX ix_prediction_events_fk_0 ON prediction_events (org_id);
CREATE INDEX ix_prediction_events_fk_1 ON prediction_events (org_id, prediction_id);
CREATE INDEX ix_prediction_events_fk_2 ON prediction_events (org_id, actor_member_id);

CREATE TABLE prediction_evidence (
	org_id UUID NOT NULL, 
	prediction_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	CONSTRAINT pk_prediction_evidence PRIMARY KEY (org_id, prediction_id, evidence_id)
)

;
CREATE INDEX ix_prediction_evidence_fk_0 ON prediction_evidence (org_id);
CREATE INDEX ix_prediction_evidence_fk_1 ON prediction_evidence (org_id, prediction_id);
CREATE INDEX ix_prediction_evidence_fk_2 ON prediction_evidence (org_id, evidence_id);

CREATE TABLE knowledge_items (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	title TEXT NOT NULL, 
	owner_member_id UUID NOT NULL, 
	current_revision_id UUID, 
	published_publication_id UUID, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_knowledge_items PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_items_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_knowledge_items_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_knowledge_items_title_nonempty CHECK (btrim(title)<>'')
)

;
CREATE INDEX ix_knowledge_items_fk_0 ON knowledge_items (org_id);
CREATE INDEX ix_knowledge_items_fk_1 ON knowledge_items (org_id, owner_member_id);
CREATE INDEX ix_knowledge_items_fk_2 ON knowledge_items (org_id, created_by);
CREATE INDEX ix_knowledge_items_fk_3 ON knowledge_items (org_id, current_revision_id, id);
CREATE INDEX ix_knowledge_items_fk_4 ON knowledge_items (org_id, published_publication_id, id);

CREATE TABLE knowledge_revisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	knowledge_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	title TEXT NOT NULL, 
	body_text TEXT NOT NULL, 
	knowledge_type TEXT NOT NULL, 
	browse_category TEXT NOT NULL, 
	tags JSONB DEFAULT '[]' NOT NULL, 
	valid_from TIMESTAMP WITH TIME ZONE, 
	valid_until TIMESTAMP WITH TIME ZONE, 
	limitations TEXT, 
	origin TEXT NOT NULL, 
	source_report_id UUID, 
	created_by UUID NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_knowledge_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_revisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_knowledge_revisions_0 CHECK (knowledge_type IN ('fact','content_atom','method_rule','case_experience','project_related')), 
	CONSTRAINT ck_knowledge_revisions_1 CHECK (browse_category IN ('genre','quote','payoff','failure','dna_case')), 
	CONSTRAINT ck_knowledge_revisions_2 CHECK (origin IN ('manual','analysis')), 
	CONSTRAINT ck_knowledge_revisions_3 CHECK (origin<>'analysis' OR source_report_id IS NOT NULL), 
	CONSTRAINT ck_knowledge_revisions_4 CHECK (btrim(title)<>'' AND btrim(body_text)<>''), 
	CONSTRAINT ck_knowledge_revisions_5 CHECK (valid_until>valid_from), 
	CONSTRAINT uq_knowledge_revisions_0 UNIQUE (org_id, knowledge_id, version_no), 
	CONSTRAINT uq_knowledge_revisions_1 UNIQUE (org_id, id, knowledge_id), 
	CONSTRAINT ck_knowledge_revisions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_knowledge_revisions_title_nonempty CHECK (btrim(title)<>''), 
	CONSTRAINT ck_knowledge_revisions_body_text_nonempty CHECK (btrim(body_text)<>''), 
	CONSTRAINT ck_knowledge_revisions_knowledge_type_nonempty CHECK (btrim(knowledge_type)<>''), 
	CONSTRAINT ck_knowledge_revisions_browse_category_nonempty CHECK (btrim(browse_category)<>''), 
	CONSTRAINT ck_knowledge_revisions_tags CHECK (jsonb_typeof(tags) = 'array'), 
	CONSTRAINT ck_knowledge_revisions_origin_nonempty CHECK (btrim(origin)<>''), 
	CONSTRAINT ck_knowledge_revisions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_knowledge_revisions_fk_0 ON knowledge_revisions (org_id);
CREATE INDEX ix_knowledge_revisions_fk_1 ON knowledge_revisions (org_id, knowledge_id);
CREATE INDEX ix_knowledge_revisions_fk_2 ON knowledge_revisions (org_id, source_report_id);
CREATE INDEX ix_knowledge_revisions_fk_3 ON knowledge_revisions (org_id, created_by);

CREATE TABLE knowledge_businesses (
	org_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	business_code TEXT NOT NULL, 
	CONSTRAINT pk_knowledge_businesses PRIMARY KEY (org_id, revision_id, business_code), 
	CONSTRAINT ck_knowledge_businesses_business_code_nonempty CHECK (btrim(business_code)<>'')
)

;
CREATE INDEX ix_knowledge_businesses_business_code_org_id_revision_id ON knowledge_businesses (business_code, org_id, revision_id);
CREATE INDEX ix_knowledge_businesses_fk_0 ON knowledge_businesses (org_id);
CREATE INDEX ix_knowledge_businesses_fk_1 ON knowledge_businesses (org_id, revision_id);
CREATE INDEX ix_knowledge_businesses_fk_2 ON knowledge_businesses (business_code);

CREATE TABLE knowledge_evidence (
	org_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	claim_path TEXT NOT NULL, 
	CONSTRAINT pk_knowledge_evidence PRIMARY KEY (org_id, revision_id, claim_path, evidence_id), 
	CONSTRAINT ck_knowledge_evidence_0 CHECK (btrim(claim_path)<>''), 
	CONSTRAINT ck_knowledge_evidence_claim_path_nonempty CHECK (btrim(claim_path)<>'')
)

;
CREATE INDEX ix_knowledge_evidence_fk_0 ON knowledge_evidence (org_id);
CREATE INDEX ix_knowledge_evidence_fk_1 ON knowledge_evidence (org_id, revision_id);
CREATE INDEX ix_knowledge_evidence_fk_2 ON knowledge_evidence (org_id, evidence_id);

CREATE TABLE knowledge_relations (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	from_revision_id UUID NOT NULL, 
	to_revision_id UUID NOT NULL, 
	relation_kind TEXT NOT NULL, 
	reason TEXT, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_knowledge_relations PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_relations_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_knowledge_relations_0 CHECK (relation_kind IN ('supports','contradicts','related','derived_from')), 
	CONSTRAINT ck_knowledge_relations_1 CHECK (from_revision_id<>to_revision_id), 
	CONSTRAINT uq_knowledge_relations_0 UNIQUE (org_id, from_revision_id, to_revision_id, relation_kind), 
	CONSTRAINT ck_knowledge_relations_relation_kind_nonempty CHECK (btrim(relation_kind)<>'')
)

;
CREATE INDEX ix_knowledge_relations_fk_0 ON knowledge_relations (org_id);
CREATE INDEX ix_knowledge_relations_fk_1 ON knowledge_relations (org_id, from_revision_id);
CREATE INDEX ix_knowledge_relations_fk_2 ON knowledge_relations (org_id, to_revision_id);
CREATE INDEX ix_knowledge_relations_fk_3 ON knowledge_relations (org_id, created_by);

CREATE TABLE review_requests (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	purpose TEXT NOT NULL, 
	knowledge_revision_id UUID, 
	report_id UUID, 
	evaluation_id UUID, 
	standard_revision_id UUID, 
	input_sha256 CHAR(64) NOT NULL, 
	requested_by UUID NOT NULL, 
	CONSTRAINT pk_review_requests PRIMARY KEY (id), 
	CONSTRAINT uq_review_requests_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_review_requests_0 CHECK (purpose IN ('knowledge_release','report_review','evaluation_review','standard_approval')), 
	CONSTRAINT ck_review_requests_1 CHECK (num_nonnulls(knowledge_revision_id,report_id,evaluation_id,standard_revision_id)=1), 
	CONSTRAINT ck_review_requests_2 CHECK ((purpose='knowledge_release')=(knowledge_revision_id IS NOT NULL)), 
	CONSTRAINT ck_review_requests_3 CHECK ((purpose='report_review')=(report_id IS NOT NULL)), 
	CONSTRAINT ck_review_requests_4 CHECK ((purpose='evaluation_review')=(evaluation_id IS NOT NULL)), 
	CONSTRAINT ck_review_requests_5 CHECK ((purpose='standard_approval')=(standard_revision_id IS NOT NULL)), 
	CONSTRAINT ck_review_requests_purpose_nonempty CHECK (btrim(purpose)<>''), 
	CONSTRAINT ck_review_requests_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_review_requests_fk_0 ON review_requests (org_id);
CREATE INDEX ix_review_requests_fk_1 ON review_requests (org_id, knowledge_revision_id);
CREATE INDEX ix_review_requests_fk_2 ON review_requests (org_id, report_id);
CREATE INDEX ix_review_requests_fk_3 ON review_requests (org_id, evaluation_id);
CREATE INDEX ix_review_requests_fk_4 ON review_requests (org_id, standard_revision_id);
CREATE INDEX ix_review_requests_fk_5 ON review_requests (org_id, requested_by);
CREATE UNIQUE INDEX ix_review_requests_org_id_purpose_evaluation_id ON review_requests (org_id, purpose, evaluation_id) WHERE evaluation_id IS NOT NULL;
CREATE UNIQUE INDEX ix_review_requests_org_id_purpose_knowledge_revision_id ON review_requests (org_id, purpose, knowledge_revision_id) WHERE knowledge_revision_id IS NOT NULL;
CREATE UNIQUE INDEX ix_review_requests_org_id_purpose_report_id ON review_requests (org_id, purpose, report_id) WHERE report_id IS NOT NULL;
CREATE UNIQUE INDEX ix_review_requests_org_id_purpose_standard_revision_id ON review_requests (org_id, purpose, standard_revision_id) WHERE standard_revision_id IS NOT NULL;

CREATE TABLE review_heads (
	org_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	reviewer_kind TEXT NOT NULL, 
	decision_id UUID NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_review_heads PRIMARY KEY (org_id, request_id, reviewer_kind), 
	CONSTRAINT ck_review_heads_0 CHECK (reviewer_kind IN ('ai','human')), 
	CONSTRAINT ck_review_heads_reviewer_kind_nonempty CHECK (btrim(reviewer_kind)<>''), 
	CONSTRAINT ck_review_heads_lock_version CHECK (lock_version > 0)
)

;
CREATE INDEX ix_review_heads_fk_0 ON review_heads (org_id);
CREATE INDEX ix_review_heads_fk_1 ON review_heads (org_id, request_id);
CREATE INDEX ix_review_heads_fk_2 ON review_heads (org_id, decision_id, request_id, reviewer_kind);

CREATE TABLE review_decisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	request_id UUID NOT NULL, 
	reviewer_kind TEXT NOT NULL, 
	reviewer_member_id UUID, 
	ai_execution_id UUID, 
	verdict TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	supersedes_decision_id UUID, 
	input_sha256 CHAR(64) NOT NULL, 
	reviewed_ai_decision_id UUID, 
	CONSTRAINT pk_review_decisions PRIMARY KEY (id), 
	CONSTRAINT uq_review_decisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_review_decisions_0 CHECK (reviewer_kind IN ('ai','human')), 
	CONSTRAINT ck_review_decisions_1 CHECK (verdict IN ('approved','rejected','needs_changes','error')), 
	CONSTRAINT ck_review_decisions_2 CHECK ((reviewer_kind='human' AND reviewer_member_id IS NOT NULL AND ai_execution_id IS NULL) OR (reviewer_kind='ai' AND reviewer_member_id IS NULL AND ai_execution_id IS NOT NULL)), 
	CONSTRAINT ck_review_decisions_3 CHECK (btrim(reason)<>''), 
	CONSTRAINT ck_review_decisions_4 CHECK (supersedes_decision_id IS DISTINCT FROM id), 
	CONSTRAINT uq_review_decisions_0 UNIQUE (org_id, id, request_id), 
	CONSTRAINT uq_review_decisions_1 UNIQUE (org_id, id, request_id, reviewer_kind), 
	CONSTRAINT ck_review_decisions_reviewer_kind_nonempty CHECK (btrim(reviewer_kind)<>''), 
	CONSTRAINT ck_review_decisions_verdict_nonempty CHECK (btrim(verdict)<>''), 
	CONSTRAINT ck_review_decisions_reason_nonempty CHECK (btrim(reason)<>''), 
	CONSTRAINT ck_review_decisions_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_review_decisions_fk_0 ON review_decisions (org_id);
CREATE INDEX ix_review_decisions_fk_1 ON review_decisions (org_id, request_id);
CREATE INDEX ix_review_decisions_fk_2 ON review_decisions (org_id, reviewer_member_id);
CREATE INDEX ix_review_decisions_fk_3 ON review_decisions (org_id, ai_execution_id);
CREATE INDEX ix_review_decisions_fk_4 ON review_decisions (org_id, reviewed_ai_decision_id, request_id);
CREATE INDEX ix_review_decisions_fk_5 ON review_decisions (org_id, supersedes_decision_id, request_id, reviewer_kind);
CREATE UNIQUE INDEX ix_review_decisions_org_id_request_id_ai_execution_id ON review_decisions (org_id, request_id, ai_execution_id) WHERE reviewer_kind='ai';
CREATE INDEX ix_review_decisions_org_id_request_id_created_at_id ON review_decisions (org_id, request_id, created_at, id);

CREATE TABLE knowledge_publications (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	knowledge_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	review_request_id UUID NOT NULL, 
	ai_decision_id UUID NOT NULL, 
	human_decision_id UUID NOT NULL, 
	published_by UUID NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_knowledge_publications PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_publications_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_knowledge_publications_0 UNIQUE (org_id, revision_id), 
	CONSTRAINT uq_knowledge_publications_1 UNIQUE (org_id, id, knowledge_id)
)

;
CREATE INDEX ix_knowledge_publications_fk_0 ON knowledge_publications (org_id);
CREATE INDEX ix_knowledge_publications_fk_1 ON knowledge_publications (org_id, knowledge_id);
CREATE INDEX ix_knowledge_publications_fk_2 ON knowledge_publications (org_id, review_request_id);
CREATE INDEX ix_knowledge_publications_fk_3 ON knowledge_publications (org_id, published_by);
CREATE INDEX ix_knowledge_publications_fk_4 ON knowledge_publications (org_id, revision_id, knowledge_id);
CREATE INDEX ix_knowledge_publications_fk_5 ON knowledge_publications (org_id, ai_decision_id, review_request_id);
CREATE INDEX ix_knowledge_publications_fk_6 ON knowledge_publications (org_id, human_decision_id, review_request_id);

CREATE TABLE search_documents (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	publication_id UUID NOT NULL, 
	revision_id UUID NOT NULL, 
	document_text TEXT NOT NULL, 
	search_vector TSVECTOR NOT NULL, 
	index_config_version TEXT NOT NULL, 
	indexed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_search_documents PRIMARY KEY (id), 
	CONSTRAINT uq_search_documents_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_search_documents_0 UNIQUE (org_id, publication_id, index_config_version), 
	CONSTRAINT ck_search_documents_document_text_nonempty CHECK (btrim(document_text)<>''), 
	CONSTRAINT ck_search_documents_index_config_version_nonempty CHECK (btrim(index_config_version)<>'')
)

;
CREATE INDEX ix_search_documents_fk_0 ON search_documents (org_id);
CREATE INDEX ix_search_documents_fk_1 ON search_documents (org_id, publication_id);
CREATE INDEX ix_search_documents_fk_2 ON search_documents (org_id, revision_id);
CREATE INDEX ix_search_documents_search_vector ON search_documents USING gin (search_vector);

CREATE TABLE embeddings (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	search_document_id UUID NOT NULL, 
	chunk_no INTEGER NOT NULL, 
	start_offset INTEGER NOT NULL, 
	end_offset INTEGER NOT NULL, 
	embedding_model TEXT NOT NULL, 
	model_version TEXT NOT NULL, 
	dimensions INTEGER NOT NULL, 
	embedding VECTOR NOT NULL, 
	content_sha256 CHAR(64) NOT NULL, 
	CONSTRAINT pk_embeddings PRIMARY KEY (id), 
	CONSTRAINT uq_embeddings_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_embeddings_0 CHECK (chunk_no>=0), 
	CONSTRAINT ck_embeddings_1 CHECK (0<=start_offset AND start_offset<end_offset), 
	CONSTRAINT ck_embeddings_2 CHECK (dimensions>0 AND vector_dims(embedding)=dimensions), 
	CONSTRAINT uq_embeddings_0 UNIQUE (org_id, search_document_id, chunk_no, embedding_model, model_version), 
	CONSTRAINT ck_embeddings_embedding_model_nonempty CHECK (btrim(embedding_model)<>''), 
	CONSTRAINT ck_embeddings_model_version_nonempty CHECK (btrim(model_version)<>''), 
	CONSTRAINT ck_embeddings_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_embeddings_fk_0 ON embeddings (org_id);
CREATE INDEX ix_embeddings_fk_1 ON embeddings (org_id, search_document_id);