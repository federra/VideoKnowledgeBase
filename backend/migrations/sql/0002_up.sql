
CREATE TABLE sources (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	name TEXT NOT NULL, 
	business_code TEXT NOT NULL, 
	platform_code TEXT NOT NULL, 
	target_kind TEXT NOT NULL, 
	keyword TEXT, 
	board_code TEXT, 
	account_id UUID, 
	content_id UUID, 
	enabled BOOLEAN DEFAULT false NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_sources PRIMARY KEY (id), 
	CONSTRAINT uq_sources_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_sources_0 CHECK (target_kind IN ('keyword','account','content','board')), 
	CONSTRAINT ck_sources_1 CHECK (num_nonnulls(keyword,board_code,account_id,content_id)=1), 
	CONSTRAINT ck_sources_2 CHECK ((target_kind='keyword')=(keyword IS NOT NULL)), 
	CONSTRAINT ck_sources_3 CHECK ((target_kind='board')=(board_code IS NOT NULL)), 
	CONSTRAINT ck_sources_4 CHECK ((target_kind='account')=(account_id IS NOT NULL)), 
	CONSTRAINT ck_sources_5 CHECK ((target_kind='content')=(content_id IS NOT NULL)), 
	CONSTRAINT ck_sources_6 CHECK (keyword IS NULL OR btrim(keyword)<>''), 
	CONSTRAINT ck_sources_7 CHECK (board_code IS NULL OR btrim(board_code)<>''), 
	CONSTRAINT ck_sources_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_sources_name_nonempty CHECK (btrim(name)<>''), 
	CONSTRAINT ck_sources_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_sources_platform_code_nonempty CHECK (btrim(platform_code)<>''), 
	CONSTRAINT ck_sources_target_kind_nonempty CHECK (btrim(target_kind)<>'')
)

;
CREATE INDEX ix_sources_fk_0 ON sources (org_id);
CREATE INDEX ix_sources_fk_1 ON sources (business_code);
CREATE INDEX ix_sources_fk_2 ON sources (platform_code);
CREATE INDEX ix_sources_fk_3 ON sources (org_id, account_id);
CREATE INDEX ix_sources_fk_4 ON sources (org_id, content_id);
CREATE INDEX ix_sources_fk_5 ON sources (org_id, created_by);
CREATE INDEX ix_sources_org_id_business_code_enabled ON sources (org_id, business_code, enabled);

CREATE TABLE collection_plans (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	source_id UUID NOT NULL, 
	connection_id UUID NOT NULL, 
	authorized_by UUID NOT NULL, 
	capability_code TEXT NOT NULL, 
	connector_version TEXT NOT NULL, 
	schedule_expression TEXT NOT NULL, 
	schedule_timezone TEXT DEFAULT 'Asia/Shanghai' NOT NULL, 
	enabled BOOLEAN DEFAULT false NOT NULL, 
	max_requests_per_run INTEGER DEFAULT 1 NOT NULL, 
	max_items_per_run INTEGER DEFAULT 1 NOT NULL, 
	request_options JSONB DEFAULT '{}' NOT NULL, 
	CONSTRAINT pk_collection_plans PRIMARY KEY (id), 
	CONSTRAINT uq_collection_plans_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_collection_plans_0 CHECK (max_requests_per_run>0 AND max_items_per_run>0), 
	CONSTRAINT ck_collection_plans_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_collection_plans_capability_code_nonempty CHECK (btrim(capability_code)<>''), 
	CONSTRAINT ck_collection_plans_connector_version_nonempty CHECK (btrim(connector_version)<>''), 
	CONSTRAINT ck_collection_plans_schedule_expression_nonempty CHECK (btrim(schedule_expression)<>''), 
	CONSTRAINT ck_collection_plans_schedule_timezone_nonempty CHECK (btrim(schedule_timezone)<>''), 
	CONSTRAINT ck_collection_plans_request_options CHECK (jsonb_typeof(request_options) = 'object')
)

;
CREATE INDEX ix_collection_plans_fk_0 ON collection_plans (org_id);
CREATE INDEX ix_collection_plans_fk_1 ON collection_plans (org_id, source_id);
CREATE INDEX ix_collection_plans_fk_2 ON collection_plans (org_id, connection_id);
CREATE INDEX ix_collection_plans_fk_3 ON collection_plans (org_id, authorized_by);
CREATE INDEX ix_collection_plans_org_id_source_id_enabled ON collection_plans (org_id, source_id, enabled);

CREATE TABLE collection_jobs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	source_id UUID NOT NULL, 
	connection_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	plan_id UUID, 
	capability_code TEXT NOT NULL, 
	connector_version TEXT NOT NULL, 
	business_code TEXT NOT NULL, 
	business_date DATE NOT NULL, 
	safe_request JSONB NOT NULL, 
	request_sha256 CHAR(64) NOT NULL, 
	scheduled_for TIMESTAMP WITH TIME ZONE, 
	max_requests INTEGER NOT NULL, 
	max_items INTEGER NOT NULL, 
	CONSTRAINT pk_collection_jobs PRIMARY KEY (id), 
	CONSTRAINT uq_collection_jobs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_collection_jobs_0 CHECK ((plan_id IS NULL)=(scheduled_for IS NULL)), 
	CONSTRAINT ck_collection_jobs_1 CHECK (max_requests>0 AND max_items>0), 
	CONSTRAINT uq_collection_jobs_0 UNIQUE (org_id, task_id), 
	CONSTRAINT ck_collection_jobs_capability_code_nonempty CHECK (btrim(capability_code)<>''), 
	CONSTRAINT ck_collection_jobs_connector_version_nonempty CHECK (btrim(connector_version)<>''), 
	CONSTRAINT ck_collection_jobs_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_collection_jobs_safe_request CHECK (jsonb_typeof(safe_request) = 'object'), 
	CONSTRAINT ck_collection_jobs_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_collection_jobs_fk_0 ON collection_jobs (org_id);
CREATE INDEX ix_collection_jobs_fk_1 ON collection_jobs (org_id, source_id);
CREATE INDEX ix_collection_jobs_fk_2 ON collection_jobs (org_id, connection_id);
CREATE INDEX ix_collection_jobs_fk_3 ON collection_jobs (org_id, task_id);
CREATE INDEX ix_collection_jobs_fk_4 ON collection_jobs (org_id, plan_id);
CREATE INDEX ix_collection_jobs_fk_5 ON collection_jobs (business_code);
CREATE UNIQUE INDEX ix_collection_jobs_org_id_plan_id_scheduled_for ON collection_jobs (org_id, plan_id, scheduled_for) WHERE plan_id IS NOT NULL;
CREATE INDEX ix_collection_jobs_org_id_source_id_business_date_created_at_id ON collection_jobs (org_id, source_id, business_date, created_at, id);

CREATE TABLE collection_calls (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	job_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	request_sha256 CHAR(64) NOT NULL, 
	reserved_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	http_status SMALLINT, 
	provider_code TEXT, 
	outcome TEXT, 
	returned_items INTEGER, 
	provider_reports_charged BOOLEAN, 
	billed_amount NUMERIC(20, 6), 
	currency TEXT, 
	billing_reference TEXT, 
	CONSTRAINT pk_collection_calls PRIMARY KEY (id), 
	CONSTRAINT uq_collection_calls_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_collection_calls_0 CHECK (sequence_no>0), 
	CONSTRAINT ck_collection_calls_1 CHECK (http_status BETWEEN 100 AND 599), 
	CONSTRAINT ck_collection_calls_2 CHECK (returned_items>=0), 
	CONSTRAINT ck_collection_calls_3 CHECK (outcome IN ('success','http_error','provider_error','network_error','invalid_shape')), 
	CONSTRAINT ck_collection_calls_4 CHECK ((outcome IS NULL)=(completed_at IS NULL)), 
	CONSTRAINT ck_collection_calls_5 CHECK (completed_at>=reserved_at), 
	CONSTRAINT ck_collection_calls_6 CHECK ((billed_amount IS NULL)=(currency IS NULL)), 
	CONSTRAINT ck_collection_calls_7 CHECK (billed_amount>=0), 
	CONSTRAINT uq_collection_calls_0 UNIQUE (org_id, job_id, sequence_no), 
	CONSTRAINT ck_collection_calls_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_collection_calls_fk_0 ON collection_calls (org_id);
CREATE INDEX ix_collection_calls_fk_1 ON collection_calls (org_id, job_id);
CREATE INDEX ix_collection_calls_fk_2 ON collection_calls (org_id, attempt_id);

CREATE TABLE external_accounts (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	platform_code TEXT NOT NULL, 
	platform_uid TEXT NOT NULL, 
	display_name TEXT, 
	CONSTRAINT pk_external_accounts PRIMARY KEY (id), 
	CONSTRAINT uq_external_accounts_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_external_accounts_0 CHECK (btrim(platform_uid)<>''), 
	CONSTRAINT uq_external_accounts_0 UNIQUE (org_id, platform_code, platform_uid), 
	CONSTRAINT ck_external_accounts_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_external_accounts_platform_code_nonempty CHECK (btrim(platform_code)<>''), 
	CONSTRAINT ck_external_accounts_platform_uid_nonempty CHECK (btrim(platform_uid)<>'')
)

;
CREATE INDEX ix_external_accounts_fk_0 ON external_accounts (org_id);
CREATE INDEX ix_external_accounts_fk_1 ON external_accounts (platform_code);

CREATE TABLE external_account_aliases (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	account_id UUID NOT NULL, 
	alias_kind TEXT NOT NULL, 
	alias_value TEXT NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_external_account_aliases PRIMARY KEY (id), 
	CONSTRAINT uq_external_account_aliases_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_external_account_aliases_0 CHECK (alias_kind IN ('unique_name','short_id','sec_uid')), 
	CONSTRAINT ck_external_account_aliases_1 CHECK (btrim(alias_value)<>''), 
	CONSTRAINT ck_external_account_aliases_2 CHECK (NOT(alias_kind='short_id' AND alias_value='0')), 
	CONSTRAINT uq_external_account_aliases_0 UNIQUE (org_id, account_id, alias_kind, alias_value, raw_asset_id), 
	CONSTRAINT ck_external_account_aliases_alias_kind_nonempty CHECK (btrim(alias_kind)<>''), 
	CONSTRAINT ck_external_account_aliases_alias_value_nonempty CHECK (btrim(alias_value)<>'')
)

;
CREATE INDEX ix_external_account_aliases_fk_0 ON external_account_aliases (org_id);
CREATE INDEX ix_external_account_aliases_fk_1 ON external_account_aliases (org_id, account_id);
CREATE INDEX ix_external_account_aliases_fk_2 ON external_account_aliases (org_id, raw_asset_id);

CREATE TABLE external_contents (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	platform_code TEXT NOT NULL, 
	platform_content_id TEXT NOT NULL, 
	account_id UUID, 
	CONSTRAINT pk_external_contents PRIMARY KEY (id), 
	CONSTRAINT uq_external_contents_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_external_contents_0 CHECK (btrim(platform_content_id)<>''), 
	CONSTRAINT uq_external_contents_0 UNIQUE (org_id, platform_code, platform_content_id), 
	CONSTRAINT ck_external_contents_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_external_contents_platform_code_nonempty CHECK (btrim(platform_code)<>''), 
	CONSTRAINT ck_external_contents_platform_content_id_nonempty CHECK (btrim(platform_content_id)<>'')
)

;
CREATE INDEX ix_external_contents_fk_0 ON external_contents (org_id);
CREATE INDEX ix_external_contents_fk_1 ON external_contents (platform_code);
CREATE INDEX ix_external_contents_fk_2 ON external_contents (org_id, account_id);

CREATE TABLE raw_assets (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	origin TEXT NOT NULL, 
	asset_kind TEXT NOT NULL, 
	collection_job_id UUID, 
	collection_call_id UUID, 
	submitted_by UUID, 
	processing_task_id UUID, 
	parent_raw_asset_id UUID, 
	parent_artifact_version_id UUID, 
	external_content_id UUID, 
	body_text TEXT, 
	file_id UUID, 
	sha256 CHAR(64) NOT NULL, 
	normalization_version INTEGER DEFAULT 1 NOT NULL, 
	captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	provider_time_raw TEXT, 
	provider_timezone TEXT, 
	CONSTRAINT pk_raw_assets PRIMARY KEY (id), 
	CONSTRAINT uq_raw_assets_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_raw_assets_0 CHECK (origin IN ('api','upload','manual','processing')), 
	CONSTRAINT ck_raw_assets_1 CHECK (asset_kind IN ('response','description','text','media','transcript','comment')), 
	CONSTRAINT ck_raw_assets_2 CHECK (num_nonnulls(body_text,file_id)=1), 
	CONSTRAINT ck_raw_assets_3 CHECK (body_text IS NULL OR btrim(body_text)<>''), 
	CONSTRAINT ck_raw_assets_4 CHECK ((origin='api')=(collection_job_id IS NOT NULL)), 
	CONSTRAINT ck_raw_assets_5 CHECK ((origin='api')=(collection_call_id IS NOT NULL)), 
	CONSTRAINT ck_raw_assets_6 CHECK (origin NOT IN ('upload','manual') OR submitted_by IS NOT NULL), 
	CONSTRAINT ck_raw_assets_7 CHECK ((origin='processing')=(processing_task_id IS NOT NULL)), 
	CONSTRAINT ck_raw_assets_8 CHECK (num_nonnulls(parent_raw_asset_id,parent_artifact_version_id)=CASE WHEN origin='processing' THEN 1 ELSE 0 END), 
	CONSTRAINT ck_raw_assets_9 CHECK (parent_raw_asset_id IS DISTINCT FROM id), 
	CONSTRAINT ck_raw_assets_origin_nonempty CHECK (btrim(origin)<>''), 
	CONSTRAINT ck_raw_assets_asset_kind_nonempty CHECK (btrim(asset_kind)<>''), 
	CONSTRAINT ck_raw_assets_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_raw_assets_normalization_version CHECK (normalization_version = 1)
)

;
CREATE INDEX ix_raw_assets_fk_0 ON raw_assets (org_id);
CREATE INDEX ix_raw_assets_fk_1 ON raw_assets (org_id, collection_job_id);
CREATE INDEX ix_raw_assets_fk_2 ON raw_assets (org_id, collection_call_id);
CREATE INDEX ix_raw_assets_fk_3 ON raw_assets (org_id, submitted_by);
CREATE INDEX ix_raw_assets_fk_4 ON raw_assets (org_id, processing_task_id);
CREATE INDEX ix_raw_assets_fk_5 ON raw_assets (org_id, parent_raw_asset_id);
CREATE INDEX ix_raw_assets_fk_6 ON raw_assets (org_id, parent_artifact_version_id);
CREATE INDEX ix_raw_assets_fk_7 ON raw_assets (org_id, external_content_id);
CREATE INDEX ix_raw_assets_fk_8 ON raw_assets (org_id, file_id);
CREATE UNIQUE INDEX ix_raw_assets_org_id_collection_call_id_sha256 ON raw_assets (org_id, collection_call_id, sha256) WHERE collection_call_id IS NOT NULL;
CREATE INDEX ix_raw_assets_org_id_sha256 ON raw_assets (org_id, sha256);

CREATE TABLE raw_asset_events (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	event_no BIGINT NOT NULL, 
	event_kind TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	actor_member_id UUID, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_raw_asset_events PRIMARY KEY (id), 
	CONSTRAINT uq_raw_asset_events_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_raw_asset_events_0 CHECK (event_no>0), 
	CONSTRAINT ck_raw_asset_events_1 CHECK (event_kind IN ('expired','withdrawn','access_revoked','availability_restored')), 
	CONSTRAINT ck_raw_asset_events_2 CHECK (btrim(reason)<>''), 
	CONSTRAINT uq_raw_asset_events_0 UNIQUE (org_id, raw_asset_id, event_no), 
	CONSTRAINT ck_raw_asset_events_event_kind_nonempty CHECK (btrim(event_kind)<>''), 
	CONSTRAINT ck_raw_asset_events_reason_nonempty CHECK (btrim(reason)<>'')
)

;
CREATE INDEX ix_raw_asset_events_fk_0 ON raw_asset_events (org_id);
CREATE INDEX ix_raw_asset_events_fk_1 ON raw_asset_events (org_id, raw_asset_id);
CREATE INDEX ix_raw_asset_events_fk_2 ON raw_asset_events (org_id, actor_member_id);

CREATE TABLE account_observations (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	account_id UUID NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	nickname TEXT, 
	unique_name TEXT, 
	avatar_url TEXT, 
	follower_count BIGINT, 
	work_count BIGINT, 
	total_liked_count BIGINT, 
	provider_updated_at_raw TEXT, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_account_observations PRIMARY KEY (id), 
	CONSTRAINT uq_account_observations_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_account_observations_0 UNIQUE (org_id, account_id, raw_asset_id), 
	CONSTRAINT ck_account_observations_follower_count CHECK (follower_count >= 0), 
	CONSTRAINT ck_account_observations_work_count CHECK (work_count >= 0), 
	CONSTRAINT ck_account_observations_total_liked_count CHECK (total_liked_count >= 0)
)

;
CREATE INDEX ix_account_observations_fk_0 ON account_observations (org_id);
CREATE INDEX ix_account_observations_fk_1 ON account_observations (org_id, account_id);
CREATE INDEX ix_account_observations_fk_2 ON account_observations (org_id, raw_asset_id);
CREATE INDEX ix_account_observations_org_id_account_id_observed_at_id ON account_observations (org_id, account_id, observed_at, id);

CREATE TABLE content_observations (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	content_id UUID NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	description TEXT, 
	original_url TEXT, 
	cover_url TEXT, 
	source_type_raw TEXT, 
	duration_ms BIGINT, 
	published_at_raw TEXT, 
	published_at TIMESTAMP WITH TIME ZONE, 
	publish_timezone TEXT, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	provider_updated_at_raw TEXT, 
	like_count BIGINT, 
	comment_count BIGINT, 
	share_count BIGINT, 
	collect_count BIGINT, 
	repost_count BIGINT, 
	view_count BIGINT, 
	author_fans_count BIGINT, 
	image_urls JSONB, 
	source_tags JSONB, 
	CONSTRAINT pk_content_observations PRIMARY KEY (id), 
	CONSTRAINT uq_content_observations_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_content_observations_0 CHECK (published_at IS NULL OR publish_timezone IS NOT NULL OR published_at_raw ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'), 
	CONSTRAINT uq_content_observations_0 UNIQUE (org_id, content_id, raw_asset_id), 
	CONSTRAINT ck_content_observations_duration_ms CHECK (duration_ms >= 0), 
	CONSTRAINT ck_content_observations_like_count CHECK (like_count >= 0), 
	CONSTRAINT ck_content_observations_comment_count CHECK (comment_count >= 0), 
	CONSTRAINT ck_content_observations_share_count CHECK (share_count >= 0), 
	CONSTRAINT ck_content_observations_collect_count CHECK (collect_count >= 0), 
	CONSTRAINT ck_content_observations_repost_count CHECK (repost_count >= 0), 
	CONSTRAINT ck_content_observations_view_count CHECK (view_count >= 0), 
	CONSTRAINT ck_content_observations_author_fans_count CHECK (author_fans_count >= 0), 
	CONSTRAINT ck_content_observations_image_urls CHECK (jsonb_typeof(image_urls) = 'array'), 
	CONSTRAINT ck_content_observations_source_tags CHECK (jsonb_typeof(source_tags) = 'array')
)

;
CREATE INDEX ix_content_observations_fk_0 ON content_observations (org_id);
CREATE INDEX ix_content_observations_fk_1 ON content_observations (org_id, content_id);
CREATE INDEX ix_content_observations_fk_2 ON content_observations (org_id, raw_asset_id);
CREATE INDEX ix_content_observations_org_id_content_id_observed_at_id ON content_observations (org_id, content_id, observed_at, id);

CREATE TABLE intelligence_snapshots (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	source_id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	business_code TEXT NOT NULL, 
	business_date DATE NOT NULL, 
	view_kind TEXT NOT NULL, 
	version_no INTEGER NOT NULL, 
	entry_count INTEGER NOT NULL, 
	CONSTRAINT pk_intelligence_snapshots PRIMARY KEY (id), 
	CONSTRAINT uq_intelligence_snapshots_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_intelligence_snapshots_0 CHECK (view_kind IN ('account_discovery','creator_works','keyword_works','board')), 
	CONSTRAINT uq_intelligence_snapshots_0 UNIQUE (org_id, source_id, business_date, view_kind, version_no), 
	CONSTRAINT uq_intelligence_snapshots_1 UNIQUE (org_id, job_id, view_kind), 
	CONSTRAINT ck_intelligence_snapshots_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_intelligence_snapshots_view_kind_nonempty CHECK (btrim(view_kind)<>''), 
	CONSTRAINT ck_intelligence_snapshots_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_intelligence_snapshots_entry_count CHECK (entry_count >= 0)
)

;
CREATE INDEX ix_intelligence_snapshots_fk_0 ON intelligence_snapshots (org_id);
CREATE INDEX ix_intelligence_snapshots_fk_1 ON intelligence_snapshots (org_id, source_id);
CREATE INDEX ix_intelligence_snapshots_fk_2 ON intelligence_snapshots (org_id, job_id);
CREATE INDEX ix_intelligence_snapshots_fk_3 ON intelligence_snapshots (business_code);
CREATE INDEX ix_intelligence_snapshots_org_id_business_code_busin_4979e8bfbd ON intelligence_snapshots (org_id, business_code, business_date, view_kind, created_at, id);

CREATE TABLE snapshot_entries (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	snapshot_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	account_observation_id UUID, 
	content_observation_id UUID, 
	provider_rank INTEGER, 
	CONSTRAINT pk_snapshot_entries PRIMARY KEY (id), 
	CONSTRAINT uq_snapshot_entries_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_snapshot_entries_0 CHECK (position>=0 AND provider_rank>0), 
	CONSTRAINT ck_snapshot_entries_1 CHECK (num_nonnulls(account_observation_id,content_observation_id)=1), 
	CONSTRAINT uq_snapshot_entries_0 UNIQUE (org_id, snapshot_id, position)
)

;
CREATE INDEX ix_snapshot_entries_fk_0 ON snapshot_entries (org_id);
CREATE INDEX ix_snapshot_entries_fk_1 ON snapshot_entries (org_id, snapshot_id);
CREATE INDEX ix_snapshot_entries_fk_2 ON snapshot_entries (org_id, account_observation_id);
CREATE INDEX ix_snapshot_entries_fk_3 ON snapshot_entries (org_id, content_observation_id);
CREATE UNIQUE INDEX ix_snapshot_entries_org_id_snapshot_id_account_observation_id ON snapshot_entries (org_id, snapshot_id, account_observation_id) WHERE account_observation_id IS NOT NULL;
CREATE UNIQUE INDEX ix_snapshot_entries_org_id_snapshot_id_content_observation_id ON snapshot_entries (org_id, snapshot_id, content_observation_id) WHERE content_observation_id IS NOT NULL;

CREATE TABLE comment_evidence (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	content_id UUID NOT NULL, 
	raw_asset_id UUID NOT NULL, 
	platform_comment_id TEXT, 
	body_text TEXT NOT NULL, 
	like_count BIGINT, 
	posted_at_raw TEXT, 
	posted_at TIMESTAMP WITH TIME ZONE, 
	posted_timezone TEXT, 
	captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	sample_position INTEGER NOT NULL, 
	CONSTRAINT pk_comment_evidence PRIMARY KEY (id), 
	CONSTRAINT uq_comment_evidence_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_comment_evidence_0 CHECK (sample_position>=0), 
	CONSTRAINT ck_comment_evidence_1 CHECK (btrim(body_text)<>''), 
	CONSTRAINT ck_comment_evidence_2 CHECK (posted_at IS NULL OR posted_timezone IS NOT NULL OR posted_at_raw ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'), 
	CONSTRAINT uq_comment_evidence_0 UNIQUE (org_id, raw_asset_id, sample_position), 
	CONSTRAINT ck_comment_evidence_body_text_nonempty CHECK (btrim(body_text)<>''), 
	CONSTRAINT ck_comment_evidence_like_count CHECK (like_count >= 0)
)

;
CREATE INDEX ix_comment_evidence_fk_0 ON comment_evidence (org_id);
CREATE INDEX ix_comment_evidence_fk_1 ON comment_evidence (org_id, content_id);
CREATE INDEX ix_comment_evidence_fk_2 ON comment_evidence (org_id, raw_asset_id);
CREATE INDEX ix_comment_evidence_org_id_content_id_captured_at_id ON comment_evidence (org_id, content_id, captured_at, id);

CREATE TABLE feedback_snapshots (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	sealed_at TIMESTAMP WITH TIME ZONE, 
	snapshot_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	task_id UUID NOT NULL, 
	ai_execution_id UUID NOT NULL, 
	sampling_description TEXT NOT NULL, 
	sample_count INTEGER NOT NULL, 
	classified_count INTEGER NOT NULL, 
	coverage_note TEXT NOT NULL, 
	summary TEXT, 
	CONSTRAINT pk_feedback_snapshots PRIMARY KEY (id), 
	CONSTRAINT uq_feedback_snapshots_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_feedback_snapshots_0 CHECK (sample_count>0 AND classified_count<=sample_count), 
	CONSTRAINT ck_feedback_snapshots_1 CHECK (btrim(sampling_description)<>''), 
	CONSTRAINT uq_feedback_snapshots_0 UNIQUE (org_id, snapshot_id, version_no), 
	CONSTRAINT uq_feedback_snapshots_1 UNIQUE (org_id, task_id), 
	CONSTRAINT ck_feedback_snapshots_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_feedback_snapshots_sampling_description_nonempty CHECK (btrim(sampling_description)<>''), 
	CONSTRAINT ck_feedback_snapshots_sample_count CHECK (sample_count >= 0), 
	CONSTRAINT ck_feedback_snapshots_classified_count CHECK (classified_count >= 0), 
	CONSTRAINT ck_feedback_snapshots_coverage_note_nonempty CHECK (btrim(coverage_note)<>'')
)

;
CREATE INDEX ix_feedback_snapshots_fk_0 ON feedback_snapshots (org_id);
CREATE INDEX ix_feedback_snapshots_fk_1 ON feedback_snapshots (org_id, snapshot_id);
CREATE INDEX ix_feedback_snapshots_fk_2 ON feedback_snapshots (org_id, task_id);
CREATE INDEX ix_feedback_snapshots_fk_3 ON feedback_snapshots (org_id, ai_execution_id);

CREATE TABLE feedback_comments (
	org_id UUID NOT NULL, 
	feedback_id UUID NOT NULL, 
	comment_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	CONSTRAINT pk_feedback_comments PRIMARY KEY (org_id, feedback_id, comment_id), 
	CONSTRAINT ck_feedback_comments_0 CHECK (position>=0), 
	CONSTRAINT uq_feedback_comments_0 UNIQUE (org_id, feedback_id, position)
)

;
CREATE INDEX ix_feedback_comments_fk_0 ON feedback_comments (org_id);
CREATE INDEX ix_feedback_comments_fk_1 ON feedback_comments (org_id, feedback_id);
CREATE INDEX ix_feedback_comments_fk_2 ON feedback_comments (org_id, comment_id);

CREATE TABLE feedback_claims (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	feedback_id UUID NOT NULL, 
	kind TEXT NOT NULL, 
	claim_key TEXT NOT NULL, 
	text TEXT NOT NULL, 
	details JSONB DEFAULT '{}' NOT NULL, 
	support_count INTEGER NOT NULL, 
	CONSTRAINT pk_feedback_claims PRIMARY KEY (id), 
	CONSTRAINT uq_feedback_claims_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_feedback_claims_0 CHECK (kind IN ('emotion','finding','expectation','suggestion')), 
	CONSTRAINT ck_feedback_claims_1 CHECK (btrim(claim_key)<>'' AND btrim(text)<>''), 
	CONSTRAINT uq_feedback_claims_0 UNIQUE (org_id, feedback_id, claim_key), 
	CONSTRAINT uq_feedback_claims_1 UNIQUE (org_id, id, feedback_id), 
	CONSTRAINT ck_feedback_claims_kind_nonempty CHECK (btrim(kind)<>''), 
	CONSTRAINT ck_feedback_claims_claim_key_nonempty CHECK (btrim(claim_key)<>''), 
	CONSTRAINT ck_feedback_claims_text_nonempty CHECK (btrim(text)<>''), 
	CONSTRAINT ck_feedback_claims_details CHECK (jsonb_typeof(details) = 'object'), 
	CONSTRAINT ck_feedback_claims_support_count CHECK (support_count >= 0)
)

;
CREATE INDEX ix_feedback_claims_fk_0 ON feedback_claims (org_id);
CREATE INDEX ix_feedback_claims_fk_1 ON feedback_claims (org_id, feedback_id);

CREATE TABLE feedback_claim_evidence (
	org_id UUID NOT NULL, 
	feedback_id UUID NOT NULL, 
	claim_id UUID NOT NULL, 
	comment_id UUID NOT NULL, 
	CONSTRAINT pk_feedback_claim_evidence PRIMARY KEY (org_id, claim_id, comment_id)
)

;
CREATE INDEX ix_feedback_claim_evidence_fk_0 ON feedback_claim_evidence (org_id);
CREATE INDEX ix_feedback_claim_evidence_fk_1 ON feedback_claim_evidence (org_id, comment_id);
CREATE INDEX ix_feedback_claim_evidence_fk_2 ON feedback_claim_evidence (org_id, claim_id, feedback_id);
CREATE INDEX ix_feedback_claim_evidence_fk_3 ON feedback_claim_evidence (org_id, feedback_id, comment_id);