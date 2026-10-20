"""B1 SQLAlchemy Core models; dictionary profiles P/M/S/F are expanded here.

No database access at import time. Alembic history uses frozen SQL, never this module.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.dialects.postgresql.base import ischema_names

metadata = sa.MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    }
)
TABLE_GROUPS = [[], [], []]
MUTABLE = {}
SEALED = []


class ExactNumeric(sa.TypeDecorator):
    """Reject values PostgreSQL numeric(20,6) would silently round."""

    impl = sa.Numeric(20, 6)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (float, bool)):
            raise TypeError("Exact numeric values require Decimal, integer or decimal text.")
        try:
            number = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Invalid exact decimal.") from exc
        if not number.is_finite():
            raise ValueError("Non-finite decimal is not allowed.")
        digits = list(number.as_tuple().digits)
        exponent = number.as_tuple().exponent
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if digits and (max(-exponent, 0) > 6 or len(digits) + exponent > 14):
            raise ValueError("Decimal exceeds numeric(20,6); rounding is not allowed.")
        return number


class Xid8(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "xid8"


ischema_names["xid8"] = Xid8

TYPES = {
    "u": UUID(as_uuid=True),
    "t": sa.Text(),
    "i": sa.Integer(),
    "b": sa.BigInteger(),
    "z": sa.DateTime(timezone=True),
    "d": sa.Date(),
    "j": JSONB(),
    "bool": sa.Boolean(),
    "n": ExactNumeric(),
    "h": sa.CHAR(64),
    "v": Vector(),
    "sv": TSVECTOR(),
    "small": sa.SmallInteger(),
    "xid": Xid8(),
}


def table(name, fields, *, group=0, profile="P", pk=None, mutable=(), checks=(), unique=()):
    """Explicit compact column declarations: name:type[?][=SQL default]."""
    specs = []
    if "P" in profile:
        specs += ["id:u", "org_id:u", "created_at:z=CURRENT_TIMESTAMP"]
    if "M" in profile:
        specs += ["updated_at:z=CURRENT_TIMESTAMP", "lock_version:b=1"]
    if "S" in profile:
        specs += ["sealed_at:z?"]
        SEALED.append(name)
    specs += fields.split()
    cols = []
    for spec in specs:
        key, typ = spec.split(":", 1)
        typ, sep, default = typ.partition("=")
        nullable = typ.endswith("?")
        typ = typ.rstrip("?")
        cols.append(
            sa.Column(
                key, TYPES[typ], nullable=nullable, server_default=sa.text(default) if sep else None
            )
        )
    obj = sa.Table(name, metadata, *cols)
    obj.append_constraint(sa.PrimaryKeyConstraint(*(pk or ["id"])))
    if "P" in profile:
        obj.append_constraint(sa.UniqueConstraint("org_id", "id", name=f"uq_{name}_tenant_id"))
    for index, constraint in enumerate(checks):
        obj.append_constraint(sa.CheckConstraint(constraint, name=f"ck_{name}_{index}"))
    for index, keys in enumerate(unique):
        obj.append_constraint(sa.UniqueConstraint(*keys.split(), name=f"uq_{name}_{index}"))
    for col in obj.c:
        predicate = None
        if col.type.__class__ == sa.CHAR:
            predicate = f"{col.name} ~ '^[0-9a-f]{{64}}$'"
        elif col.name in ("normalization_version", "schema_version", "version_no", "lock_version"):
            predicate = f"{col.name} {'= 1' if col.name == 'normalization_version' else '> 0'}"
        elif col.name.endswith(("_count", "_tokens")) or col.name in ("byte_size", "duration_ms"):
            predicate = f"{col.name} >= 0"
        elif isinstance(col.type, JSONB):
            arrays = (
                "genre_tags",
                "tags",
                "learning_tags",
                "confirmed_genre_tags",
                "image_urls",
                "source_tags",
                "missing_inputs",
            )
            predicate = (
                f"jsonb_typeof({col.name}) = '{'array' if col.name in arrays else 'object'}'"
            )
        if isinstance(col.type, sa.Text) and not col.nullable:
            obj.append_constraint(
                sa.CheckConstraint(f"btrim({col.name})<>''", name=f"ck_{name}_{col.name}_nonempty")
            )
        if predicate:
            obj.append_constraint(sa.CheckConstraint(predicate, name=f"ck_{name}_{col.name}"))
    if "M" in profile or mutable:
        MUTABLE[name] = list(mutable) + (["updated_at", "lock_version"] if "M" in profile else [])
    TABLE_GROUPS[group].append(name)
    return obj


def enum(column, values):
    return f"{column} IN ({','.join(repr(v) for v in values.split())})"


def xor(*cols):
    return f"num_nonnulls({','.join(cols)})=1"


def index(name, cols, *, where=None, unique=False, using=None):
    t = metadata.tables[name]
    keys = cols.split()
    label = f"ix_{name}_{'_'.join(keys)}"
    if len(label) > 63:
        label = label[:52] + "_" + hashlib.sha256(label.encode()).hexdigest()[:10]
    return sa.Index(
        label,
        *(t.c[k] for k in keys),
        unique=unique,
        postgresql_where=sa.text(where) if where else None,
        **({"postgresql_using": using} if using else {}),
    )


def fk(source, columns, target, targets="id"):
    st, tt = metadata.tables[source], metadata.tables[target]
    a, b = columns.split(), targets.split()
    if "org_id" in st.c and "org_id" in tt.c:
        a, b = ["org_id", *a], ["org_id", *b]
    number = len([c for c in st.constraints if isinstance(c, sa.ForeignKeyConstraint)])
    st.append_constraint(
        sa.ForeignKeyConstraint(
            a,
            [f"{target}.{v}" for v in b],
            name=f"fk_{source}_{number}",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
    )
    # Referencing-side index, including org and multi-parent discriminators.
    index_name = f"ix_{source}_fk_{number}"
    sa.Index(index_name, *(st.c[k] for k in a))


MATERIALS = "topic script storyboard_script storyboard_image asset finished_video reference"
STATES = "queued running succeeded failed cancel_requested cancelled"
RESULTS = "completed insufficient_evidence failed"
ACTIONS = (
    "content.read evidence.read file.read content.export content.write research.submit "
    "research.run knowledge.candidate.read knowledge.edit knowledge.review.run report.review.run "
    "knowledge.review knowledge.publish report.review evaluation.review prediction.edit "
    "prediction.freeze prediction.retract standard.read standard.edit standard.approve "
    "standard.activate source.configure collection.run model.configure task.read task.manage "
    "member.manage role.manage grant.manage audit.read"
)

table(
    "organizations",
    "id:u name:t created_at:z=CURRENT_TIMESTAMP authz_version:b=1",
    profile="M",
    mutable=("name", "authz_version"),
    checks=("btrim(name)<>''", "authz_version>0"),
)
table(
    "business_lines",
    "code:t name:t",
    profile="",
    pk=["code"],
    checks=(enum("code", "motion_comic story_short ecommerce_video"), "btrim(name)<>''"),
)
table("platforms", "code:t name:t", profile="", pk=["code"], checks=("btrim(name)<>''",))
table(
    "members",
    "login_name:t display_name:t password_hash:t? disabled_at:z?",
    profile="PM",
    mutable=("login_name", "display_name", "password_hash", "disabled_at"),
    checks=("btrim(login_name)<>''", "btrim(display_name)<>''"),
)
sa.Index(
    "uq_members_login",
    metadata.tables["members"].c.org_id,
    sa.func.lower(metadata.tables["members"].c.login_name),
    unique=True,
)
table(
    "role_definitions",
    "code:t name:t description:t?",
    profile="PM",
    mutable=("name", "description"),
    unique=("org_id code",),
)
table(
    "role_actions",
    "org_id:u role_id:u action_code:t",
    profile="",
    pk=["org_id", "role_id", "action_code"],
    checks=(enum("action_code", ACTIONS),),
)
SCOPE_SLOTS = [
    "business_code",
    "source_id",
    "raw_asset_id",
    "work_id",
    "knowledge_id",
    "standard_id",
    "file_id",
    "task_id",
]
SCOPES = ["business", "source", "raw_asset", "work", "knowledge", "standard", "file", "task"]
scope_check = (
    "(scope_kind='org' AND num_nonnulls("
    + ",".join(SCOPE_SLOTS)
    + ")=0) OR ("
    + "num_nonnulls("
    + ",".join(SCOPE_SLOTS)
    + ")=1 AND ("
    + " OR ".join(
        f"(scope_kind='{kind}' AND {col} IS NOT NULL)" for kind, col in zip(SCOPES, SCOPE_SLOTS)
    )
    + "))"
)
table(
    "grants",
    "member_id:u role_id:u scope_kind:t business_code:t? source_id:u? raw_asset_id:u? "
    "work_id:u? knowledge_id:u? standard_id:u? file_id:u? task_id:u? granted_by:u "
    "expires_at:z? revoked_at:z?",
    profile="PM",
    mutable=("expires_at", "revoked_at"),
    checks=(scope_check, "expires_at IS NULL OR expires_at>created_at"),
)
table(
    "audit_events",
    "actor_member_id:u? action_code:t target_kind:t target_id:u? "
    "target_version_no:i? occurred_at:z=CURRENT_TIMESTAMP request_id:t safe_details:j='{}'",
    checks=("target_version_no>0", "btrim(request_id)<>''"),
)
table(
    "file_objects",
    "storage_backend:t storage_key:t original_name:t? media_type:t byte_size:b "
    "sha256:h uploaded_by:u? validation_state:t='pending'",
    profile="PM",
    mutable=("original_name", "validation_state"),
    unique=("org_id storage_backend storage_key",),
    checks=(enum("validation_state", "pending accepted rejected"), "btrim(media_type)<>''"),
)
table(
    "provider_connections",
    "provider_code:t name:t secret_ref:t enabled:bool=false",
    profile="PM",
    mutable=("name", "secret_ref", "enabled"),
    unique=("org_id name",),
    checks=("btrim(name)<>''", "secret_ref ~ '^[A-Z][A-Z0-9_]*$'"),
)
table(
    "standards",
    "code:t kind:t business_code:t name:t active_revision_id:u?",
    profile="PM",
    mutable=("name", "active_revision_id"),
    unique=("org_id code",),
    checks=(enum("kind", "rubric analysis_template prompt parsing_template"),),
)
table(
    "standard_revisions",
    "standard_id:u version_no:i schema_version:i=1 material_kind:t? "
    "definition:j origin_kind:t provenance_note:t content_sha256:h created_by:u",
    checks=(
        enum("material_kind", MATERIALS),
        enum("origin_kind", "expert_baseline manual_configuration learning_candidate"),
        "btrim(provenance_note)<>''",
    ),
    unique=("org_id standard_id version_no", "org_id id standard_id"),
)
table(
    "ai_config_revisions",
    "config_key:t version_no:i task_kind:t provider_connection_id:u "
    "model_identifier:t prompt_revision_id:u? parameters:j='{}' output_schema:j "
    "content_sha256:h created_by:u",
    unique=("org_id config_key version_no",),
    checks=("btrim(model_identifier)<>''",),
)
table(
    "tasks",
    "kind:t handler_version:t business_code:t? source_id:u? raw_asset_id:u? work_id:u? "
    "knowledge_id:u? standard_id:u? file_id:u? requested_by:u? execution_authorized_by:u? "
    "inputs_sealed_at:z? outputs_sealed_at:z? inputs_frozen_at:z? business_outcome:t? "
    "max_attempts:i=1 max_external_calls:i=0 state:t='queued' idempotency_key:t input_sha256:h "
    "normalization_version:i=1 available_at:z=CURRENT_TIMESTAMP started_at:z? finished_at:z? "
    "cancel_requested_at:z? safe_error_code:t?",
    profile="PM",
    mutable=(
        "execution_authorized_by",
        "inputs_sealed_at",
        "outputs_sealed_at",
        "inputs_frozen_at",
        "business_outcome",
        "max_attempts",
        "max_external_calls",
        "state",
        "available_at",
        "started_at",
        "finished_at",
        "cancel_requested_at",
        "safe_error_code",
    ),
    checks=(
        enum("state", STATES),
        enum("business_outcome", "completed insufficient_evidence"),
        "num_nonnulls(source_id,raw_asset_id,work_id,knowledge_id,standard_id,file_id)>0",
        "max_attempts>0 AND max_external_calls>=0",
        "(state='succeeded')=(business_outcome IS NOT NULL)",
        "(state IN ('succeeded','failed','cancelled'))=(finished_at IS NOT NULL)",
        "finished_at IS NULL OR started_at IS NULL OR finished_at>=started_at",
        "btrim(kind)<>'' AND btrim(handler_version)<>'' AND btrim(idempotency_key)<>''",
    ),
    unique=("org_id kind idempotency_key",),
)
INPUT_TARGETS = [
    "raw_asset",
    "artifact_version",
    "input_set",
    "snapshot",
    "feedback",
    "knowledge_revision",
    "standard_revision",
    "ai_config_revision",
    "review_request",
]
OUTPUT_TARGETS = [
    "raw_asset",
    "snapshot",
    "feedback",
    "report",
    "evaluation",
    "prediction",
    "knowledge_revision",
    "ai_execution",
    "review_decision",
    "artifact_version",
]
for name, targets in [("task_inputs", INPUT_TARGETS), ("task_outputs", OUTPUT_TARGETS)]:
    table(
        name,
        "org_id:u task_id:u position:i role:t " + " ".join(f"{v}_id:u?" for v in targets),
        profile="",
        pk=["org_id", "task_id", "position"],
        checks=("position>=0", "btrim(role)<>''", xor(*(f"{v}_id" for v in targets))),
    )
table(
    "task_attempts",
    "task_id:u attempt_no:i worker_token:u lease_expires_at:z "
    "started_at:z=CURRENT_TIMESTAMP finished_at:z? outcome:t? safe_error_code:t? provider_code:t?",
    mutable=("lease_expires_at", "finished_at", "outcome", "safe_error_code", "provider_code"),
    unique=("org_id task_id attempt_no",),
    checks=(
        "attempt_no>0",
        enum("outcome", "succeeded failed cancelled lease_lost"),
        "(finished_at IS NULL)=(outcome IS NULL)",
        "finished_at>=started_at",
        "lease_expires_at>started_at",
    ),
)
index("task_attempts", "org_id task_id", where="finished_at IS NULL", unique=True)
index("task_attempts", "lease_expires_at", where="finished_at IS NULL")

# B1-b: collection, immutable observations and frozen feedback.
table(
    "sources",
    "name:t business_code:t platform_code:t target_kind:t keyword:t? board_code:t? "
    "account_id:u? content_id:u? enabled:bool=false archived_at:z? created_by:u",
    group=1,
    profile="PM",
    mutable=("name", "enabled", "archived_at"),
    checks=(
        enum("target_kind", "keyword account content board"),
        xor("keyword", "board_code", "account_id", "content_id"),
        "(target_kind='keyword')=(keyword IS NOT NULL)",
        "(target_kind='board')=(board_code IS NOT NULL)",
        "(target_kind='account')=(account_id IS NOT NULL)",
        "(target_kind='content')=(content_id IS NOT NULL)",
        "archived_at IS NULL OR NOT enabled",
        "keyword IS NULL OR btrim(keyword)<>''",
        "board_code IS NULL OR btrim(board_code)<>''",
    ),
)
table(
    "collection_plans",
    "source_id:u connection_id:u authorized_by:u capability_code:t "
    "connector_version:t schedule_expression:t schedule_timezone:t='Asia/Shanghai' "
    "enabled:bool=false max_requests_per_run:i=1 max_items_per_run:i=1 request_options:j='{}'",
    group=1,
    profile="PM",
    mutable=(
        "authorized_by",
        "schedule_expression",
        "schedule_timezone",
        "enabled",
        "max_requests_per_run",
        "max_items_per_run",
        "request_options",
    ),
    checks=("max_requests_per_run>0 AND max_items_per_run>0",),
)
table(
    "collection_jobs",
    "source_id:u connection_id:u task_id:u plan_id:u? capability_code:t "
    "connector_version:t business_code:t business_date:d safe_request:j request_sha256:h "
    "scheduled_for:z? max_requests:i max_items:i",
    group=1,
    unique=("org_id task_id",),
    checks=("(plan_id IS NULL)=(scheduled_for IS NULL)", "max_requests>0 AND max_items>0"),
)
index("collection_jobs", "org_id plan_id scheduled_for", where="plan_id IS NOT NULL", unique=True)
table(
    "collection_calls",
    "job_id:u attempt_id:u sequence_no:i request_sha256:h "
    "reserved_at:z=CURRENT_TIMESTAMP completed_at:z? http_status:small? provider_code:t? "
    "outcome:t? returned_items:i? provider_reports_charged:bool? billed_amount:n? currency:t? "
    "billing_reference:t?",
    group=1,
    mutable=(
        "completed_at",
        "http_status",
        "provider_code",
        "outcome",
        "returned_items",
        "provider_reports_charged",
        "billed_amount",
        "currency",
        "billing_reference",
    ),
    unique=("org_id job_id sequence_no",),
    checks=(
        "sequence_no>0",
        "http_status BETWEEN 100 AND 599",
        "returned_items>=0",
        enum("outcome", "success http_error provider_error network_error invalid_shape"),
        "(outcome IS NULL)=(completed_at IS NULL)",
        "completed_at>=reserved_at",
        "(billed_amount IS NULL)=(currency IS NULL)",
        "billed_amount>=0",
    ),
)
table(
    "external_accounts",
    "platform_code:t platform_uid:t display_name:t?",
    group=1,
    profile="PM",
    mutable=("display_name",),
    unique=("org_id platform_code platform_uid",),
    checks=("btrim(platform_uid)<>''",),
)
table(
    "external_account_aliases",
    "account_id:u alias_kind:t alias_value:t raw_asset_id:u observed_at:z",
    group=1,
    unique=("org_id account_id alias_kind alias_value raw_asset_id",),
    checks=(
        enum("alias_kind", "unique_name short_id sec_uid"),
        "btrim(alias_value)<>''",
        "NOT(alias_kind='short_id' AND alias_value='0')",
    ),
)
table(
    "external_contents",
    "platform_code:t platform_content_id:t account_id:u?",
    group=1,
    profile="PM",
    mutable=("account_id",),
    unique=("org_id platform_code platform_content_id",),
    checks=("btrim(platform_content_id)<>''",),
)
table(
    "raw_assets",
    "origin:t asset_kind:t collection_job_id:u? collection_call_id:u? submitted_by:u? "
    "processing_task_id:u? parent_raw_asset_id:u? parent_artifact_version_id:u? external_content_id:u? "
    "body_text:t? file_id:u? sha256:h normalization_version:i=1 captured_at:z provider_time_raw:t? "
    "provider_timezone:t?",
    group=1,
    checks=(
        enum("origin", "api upload manual processing"),
        enum("asset_kind", "response description text media transcript comment"),
        xor("body_text", "file_id"),
        "body_text IS NULL OR btrim(body_text)<>''",
        "(origin='api')=(collection_job_id IS NOT NULL)",
        "(origin='api')=(collection_call_id IS NOT NULL)",
        "origin NOT IN ('upload','manual') OR submitted_by IS NOT NULL",
        "(origin='processing')=(processing_task_id IS NOT NULL)",
        "num_nonnulls(parent_raw_asset_id,parent_artifact_version_id)=CASE WHEN origin='processing' THEN 1 ELSE 0 END",
        "parent_raw_asset_id IS DISTINCT FROM id",
    ),
)
index(
    "raw_assets",
    "org_id collection_call_id sha256",
    where="collection_call_id IS NOT NULL",
    unique=True,
)
table(
    "raw_asset_events",
    "raw_asset_id:u event_no:b event_kind:t reason:t actor_member_id:u? "
    "occurred_at:z=CURRENT_TIMESTAMP",
    group=1,
    unique=("org_id raw_asset_id event_no",),
    checks=(
        "event_no>0",
        enum("event_kind", "expired withdrawn access_revoked availability_restored"),
        "btrim(reason)<>''",
    ),
)
table(
    "account_observations",
    "account_id:u raw_asset_id:u nickname:t? unique_name:t? avatar_url:t? "
    "follower_count:b? work_count:b? total_liked_count:b? provider_updated_at_raw:t? observed_at:z",
    group=1,
    unique=("org_id account_id raw_asset_id",),
)
table(
    "content_observations",
    "content_id:u raw_asset_id:u description:t? original_url:t? cover_url:t? "
    "source_type_raw:t? duration_ms:b? published_at_raw:t? published_at:z? publish_timezone:t? "
    "observed_at:z provider_updated_at_raw:t? like_count:b? comment_count:b? share_count:b? "
    "collect_count:b? repost_count:b? view_count:b? author_fans_count:b? image_urls:j? source_tags:j?",
    group=1,
    unique=("org_id content_id raw_asset_id",),
    checks=(
        "published_at IS NULL OR publish_timezone IS NOT NULL OR published_at_raw ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'",
    ),
)
table(
    "intelligence_snapshots",
    "source_id:u job_id:u business_code:t business_date:d view_kind:t version_no:i entry_count:i",
    group=1,
    profile="PS",
    unique=("org_id source_id business_date view_kind version_no", "org_id job_id view_kind"),
    checks=(enum("view_kind", "account_discovery creator_works keyword_works board"),),
)
table(
    "snapshot_entries",
    "snapshot_id:u position:i account_observation_id:u? content_observation_id:u? provider_rank:i?",
    group=1,
    unique=("org_id snapshot_id position",),
    checks=(
        "position>=0 AND provider_rank>0",
        xor("account_observation_id", "content_observation_id"),
    ),
)
for col in ["account_observation_id", "content_observation_id"]:
    index("snapshot_entries", f"org_id snapshot_id {col}", where=f"{col} IS NOT NULL", unique=True)
table(
    "comment_evidence",
    "content_id:u raw_asset_id:u platform_comment_id:t? body_text:t username:t? "
    "like_count:b? posted_at_raw:t? posted_at:z? posted_timezone:t? captured_at:z sample_position:i",
    group=1,
    unique=("org_id raw_asset_id sample_position",),
    checks=(
        "sample_position>=0",
        "btrim(body_text)<>''",
        "posted_at IS NULL OR posted_timezone IS NOT NULL OR posted_at_raw ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$'",
    ),
)
table(
    "feedback_snapshots",
    "snapshot_id:u version_no:i task_id:u ai_execution_id:u sampling_description:t "
    "sample_count:i classified_count:i coverage_note:t summary:t?",
    group=1,
    profile="PS",
    unique=("org_id snapshot_id version_no", "org_id task_id"),
    checks=("sample_count>0 AND classified_count<=sample_count", "btrim(sampling_description)<>''"),
)
table(
    "feedback_comments",
    "org_id:u feedback_id:u comment_id:u position:i",
    group=1,
    profile="",
    pk=["org_id", "feedback_id", "comment_id"],
    unique=("org_id feedback_id position",),
    checks=("position>=0",),
)
table(
    "feedback_claims",
    "feedback_id:u kind:t claim_key:t text:t details:j='{}' support_count:i",
    group=1,
    unique=("org_id feedback_id claim_key", "org_id id feedback_id"),
    checks=(
        enum("kind", "emotion finding expectation suggestion"),
        "btrim(claim_key)<>'' AND btrim(text)<>''",
    ),
)
table(
    "feedback_claim_evidence",
    "org_id:u feedback_id:u claim_id:u comment_id:u",
    group=1,
    profile="",
    pk=["org_id", "claim_id", "comment_id"],
)

# S06.4 immutable same-day projection from one sealed feedback version.
table(
    "insight_reports", "feedback_id:u task_id:u schema_version:i=1 body:j", group=2,
    unique=("org_id feedback_id schema_version", "org_id task_id"),
    checks=("schema_version=1",),
)

# B1-c: work/material identities, frozen inputs/results, review and publication.
table(
    "works",
    "business_code:t work_number:t name:t genre_tags:j='[]' total_episode_count:i? "
    "cover_file_id:u? cover_url:t? created_by:u report_generation:b=0 latest_report_id:u?",
    group=2,
    profile="PM",
    unique=("org_id work_number",),
    mutable=(
        "name",
        "genre_tags",
        "total_episode_count",
        "cover_file_id",
        "cover_url",
        "report_generation",
        "latest_report_id",
    ),
    checks=(
        "btrim(name)<>'' AND btrim(work_number)<>''",
        "total_episode_count>0",
        "business_code='motion_comic' OR total_episode_count IS NULL",
        "report_generation>=0",
    ),
)
table(
    "content_units",
    "work_id:u unit_kind:t episode_no:i? title:t? order_key:n?",
    group=2,
    profile="PM",
    mutable=("episode_no", "title", "order_key"),
    unique=("org_id id work_id",),
    checks=(
        enum("unit_kind", "episode segment"),
        "episode_no>0",
        "unit_kind='episode' OR episode_no IS NULL",
    ),
)
index(
    "content_units",
    "org_id work_id episode_no",
    where="unit_kind='episode' AND episode_no IS NOT NULL",
    unique=True,
)
table(
    "artifacts",
    "work_id:u primary_unit_id:u? material_number:t title:t? material_kind:t "
    "current_version_id:u? created_by:u",
    group=2,
    profile="PM",
    mutable=("primary_unit_id", "title", "material_kind", "current_version_id"),
    unique=("org_id material_number", "org_id id work_id"),
    checks=(enum("material_kind", MATERIALS),),
)
table(
    "artifact_versions",
    "artifact_id:u work_id:u version_no:i title:t? material_kind:t body_text:t? "
    "file_id:u? content_sha256:h normalization_version:i=1 created_by:u revision_reason:t?",
    group=2,
    profile="PS",
    unique=(
        "org_id artifact_id version_no",
        "org_id artifact_id content_sha256",
        "org_id id artifact_id",
        "org_id id work_id",
    ),
    checks=(enum("material_kind", MATERIALS), "body_text IS NULL OR btrim(body_text)<>''"),
)
table(
    "artifact_version_sources",
    "org_id:u artifact_version_id:u raw_asset_id:u role:t",
    group=2,
    profile="",
    pk=["org_id", "artifact_version_id", "raw_asset_id", "role"],
    checks=(enum("role", "primary reference transcript frame"),),
)
table(
    "artifact_version_units",
    "org_id:u artifact_version_id:u work_id:u unit_id:u "
    "episode_no_at_input:i? unit_title_at_input:t?",
    group=2,
    profile="",
    pk=["org_id", "artifact_version_id", "unit_id"],
    checks=("episode_no_at_input>0",),
)
table(
    "artifact_lineage",
    "org_id:u from_version_id:u to_version_id:u relation_kind:t",
    group=2,
    profile="",
    pk=["org_id", "from_version_id", "to_version_id", "relation_kind"],
    checks=(enum("relation_kind", "derived_from references"), "from_version_id<>to_version_id"),
)
table(
    "research_submissions",
    "work_id:u artifact_version_id:u origin:t snapshot_entry_id:u? "
    "feedback_id:u? handoff_id:u? submitted_by:u task_id:u client_request_key:t import_key:t input_sha256:h",
    group=2,
    profile="PS",
    unique=("org_id submitted_by client_request_key",),
    checks=(
        enum("origin", "intelligence upload link text"),
        "(origin='intelligence')=(snapshot_entry_id IS NOT NULL)",
        "origin='intelligence' OR feedback_id IS NULL",
        "btrim(client_request_key)<>''",
    ),
)
table(
    "preliminary_assessments",
    "submission_id:u assessed_by:u quality_grade:t? opinion:t? "
    "learning_tags:j='[]' additional_learning:t? confirmed_business_code:t "
    "confirmed_genre_tags:j='[]' work_name_at_submit:t total_episodes_at_submit:i? "
    "episode_no_at_submit:i?",
    group=2,
    unique=("org_id submission_id",),
    checks=(
        enum("quality_grade", "S A B C"),
        "total_episodes_at_submit>0 AND episode_no_at_submit>0",
        "episode_no_at_submit<=total_episodes_at_submit",
        "btrim(work_name_at_submit)<>''",
    ),
)
table(
    "input_sets",
    "work_id:u scope:t unit_id:u? artifact_id:u? business_code:t manifest_sha256:h "
    "normalization_version:i=1 total_episode_count_at_input:i? parsed_sources:j='{}'",
    group=2,
    profile="PS",
    unique=("org_id work_id manifest_sha256", "org_id id work_id"),
    checks=(
        enum("scope", "work unit artifact"),
        "total_episode_count_at_input>0",
        (
            "(scope='work' AND num_nonnulls(unit_id,artifact_id)=0) OR "
            "(scope='unit' AND unit_id IS NOT NULL AND artifact_id IS NULL) OR "
            "(scope='artifact' AND artifact_id IS NOT NULL AND unit_id IS NULL)"
        ),
    ),
)
table(
    "input_set_items",
    "org_id:u input_set_id:u work_id:u artifact_version_id:u role:t position:i",
    group=2,
    profile="",
    pk=["org_id", "input_set_id", "artifact_version_id", "role"],
    unique=("org_id input_set_id position",),
    checks=(enum("role", "primary reference"), "position>=0"),
)
table(
    "analysis_runs",
    "report_generation:b input_set_id:u task_id:u template_revision_id:u "
    "rubric_revision_id:u? ai_config_revision_id:u state:t='queued' started_at:z? finished_at:z? "
    "safe_error_code:t?",
    group=2,
    unique=("org_id task_id",),
    mutable=("state", "started_at", "finished_at", "safe_error_code"),
    checks=("report_generation>0", enum("state", STATES)),
)
table(
    "ai_executions",
    "task_id:u attempt_id:u config_revision_id:u invocation_no:i input_sha256:h "
    "input_manifest_file_id:u provider_request_id:t? started_at:z=CURRENT_TIMESTAMP finished_at:z? "
    "result_state:t? output_file_id:u? safe_error_code:t? input_tokens:b? output_tokens:b? "
    "cost_amount:n? cost_currency:t?",
    group=2,
    unique=("org_id attempt_id invocation_no",),
    mutable=(
        "provider_request_id",
        "finished_at",
        "result_state",
        "output_file_id",
        "safe_error_code",
        "input_tokens",
        "output_tokens",
        "cost_amount",
        "cost_currency",
    ),
    checks=(
        "invocation_no>0",
        enum("result_state", RESULTS),
        "(finished_at IS NULL)=(result_state IS NULL)",
        "finished_at>=started_at",
        "result_state IS DISTINCT FROM 'completed' OR output_file_id IS NOT NULL",
        "(cost_amount IS NULL)=(cost_currency IS NULL)",
        "cost_amount>=0",
    ),
)
table(
    "analysis_reports",
    "work_id:u input_set_id:u analysis_run_id:u ai_execution_id:u version_no:i "
    "coverage_kind:t schema_version:i=1 body:j missing_inputs:j='[]' result_state:t content_sha256:h",
    group=2,
    profile="PS",
    unique=("org_id work_id version_no", "org_id analysis_run_id", "org_id id work_id"),
    checks=("coverage_kind='partial'", enum("result_state", "completed insufficient_evidence")),
)
table(
    "report_units",
    "org_id:u report_id:u work_id:u unit_id:u coverage_state:t "
    "episode_no_at_report:i? unit_title_at_report:t?",
    group=2,
    profile="",
    pk=["org_id", "report_id", "unit_id"],
    checks=(
        enum("coverage_state", "analyzed missing failed insufficient_evidence"),
        "episode_no_at_report>0",
    ),
)
table(
    "evidence_refs",
    "raw_asset_id:u? artifact_version_id:u? locator_kind:t paragraph_no:i? "
    "page_no:i? start_ms:b? end_ms:b? quoted_text:t?",
    group=2,
    checks=(
        xor("raw_asset_id", "artifact_version_id"),
        (
            "COALESCE(((locator_kind='whole' AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=0) OR "
            "(locator_kind='paragraph' AND paragraph_no>0 AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=1) OR "
            "(locator_kind='page' AND page_no>0 AND num_nonnulls(paragraph_no,page_no,start_ms,end_ms)=1) OR "
            "(locator_kind='time' AND start_ms IS NOT NULL AND end_ms IS NOT NULL AND "
            "paragraph_no IS NULL AND page_no IS NULL AND start_ms>=0 AND end_ms>=start_ms)),false)"
        ),
    ),
)
table(
    "report_evidence",
    "org_id:u report_id:u evidence_id:u claim_path:t",
    group=2,
    profile="",
    pk=["org_id", "report_id", "claim_path", "evidence_id"],
    checks=("btrim(claim_path)<>''",),
)
table(
    "quality_evaluations",
    "input_set_id:u task_id:u rubric_revision_id:u ai_execution_id:u "
    "report_id:u? result_state:t quality_grade:t? schema_version:i=1 dimensions:j summary:t? content_sha256:h",
    group=2,
    profile="PS",
    unique=("org_id task_id",),
    checks=(
        enum("result_state", RESULTS),
        enum("quality_grade", "S A B C"),
        "result_state<>'insufficient_evidence' OR quality_grade IS NULL",
    ),
)
table(
    "evaluation_evidence",
    "org_id:u evaluation_id:u evidence_id:u dimension_code:t",
    group=2,
    profile="",
    pk=["org_id", "evaluation_id", "dimension_code", "evidence_id"],
)
table(
    "metric_specs",
    "code:t version_no:i name:t unit:t definition:t aggregation_kind:t denominator_definition:t?",
    group=2,
    unique=("org_id code version_no",),
    checks=(
        enum("aggregation_kind", "cumulative window_count rate"),
        "aggregation_kind<>'rate' OR (denominator_definition IS NOT NULL AND btrim(denominator_definition)<>'')",
    ),
)
PREDICTION_FIELDS = (
    "input_set_id:u metric_spec_id:u author_kind:t author_member_id:u? ai_execution_id:u? "
    "platform_code:t account_id:u? window_start_offset_seconds:b window_end_offset_seconds:b "
    "conditions:j context_kind:t='unknown' outcome_exposure:t='unknown' lower_bound:n? "
    "upper_bound:n? rationale:t uncertainty_note:t rubric_revision_id:u? prompt_revision_id:u? "
    "supersedes_prediction_id:u?"
)
pred_checks = (
    enum("author_kind", "human ai"),
    (
        "(author_kind='human' AND author_member_id IS NOT NULL AND ai_execution_id IS NULL) OR "
        "(author_kind='ai' AND author_member_id IS NULL AND ai_execution_id IS NOT NULL)"
    ),
    "window_start_offset_seconds>=0 AND window_end_offset_seconds>window_start_offset_seconds",
    "(lower_bound IS NULL)=(upper_bound IS NULL)",
    "lower_bound>=0 AND upper_bound>=lower_bound",
    enum("context_kind", "prospective_candidate retrospective unknown"),
    enum("outcome_exposure", "unobserved observed unknown"),
    "btrim(rationale)<>'' AND btrim(uncertainty_note)<>''",
)
table(
    "prediction_drafts",
    PREDICTION_FIELDS + " reliability:t",
    group=2,
    profile="PM",
    mutable=tuple(re.findall(r"(\w+):", PREDICTION_FIELDS)) + ("reliability",),
    checks=pred_checks
    + (
        enum("reliability", "estimable insufficient_evidence"),
        "(reliability='estimable')=(lower_bound IS NOT NULL)",
    ),
)
table(
    "predictions",
    PREDICTION_FIELDS + " draft_id:u draft_lock_version:b "
    "frozen_at:z=clock_timestamp() freeze_transaction:xid=pg_current_xact_id() frozen_by:u content_sha256:h",
    group=2,
    profile="PS",
    checks=pred_checks + ("lower_bound IS NOT NULL", "draft_lock_version>0"),
    unique=("org_id draft_id draft_lock_version",),
)
table(
    "prediction_events",
    "prediction_id:u event_kind:t reason:t actor_member_id:u occurred_at:z=clock_timestamp()",
    group=2,
    unique=("org_id prediction_id event_kind",),
    checks=(enum("event_kind", "freeze_confirmed retracted"), "btrim(reason)<>''"),
)
table(
    "prediction_evidence",
    "org_id:u prediction_id:u evidence_id:u",
    group=2,
    profile="",
    pk=["org_id", "prediction_id", "evidence_id"],
)
table(
    "knowledge_items",
    "title:t owner_member_id:u current_revision_id:u? published_publication_id:u? created_by:u",
    group=2,
    profile="PM",
    mutable=("title", "owner_member_id", "current_revision_id", "published_publication_id"),
)
table(
    "knowledge_revisions",
    "knowledge_id:u version_no:i title:t body_text:t knowledge_type:t "
    "browse_category:t tags:j='[]' valid_from:z? valid_until:z? limitations:t? origin:t "
    "source_report_id:u? created_by:u content_sha256:h",
    group=2,
    profile="PS",
    unique=("org_id knowledge_id version_no", "org_id id knowledge_id"),
    checks=(
        enum("knowledge_type", "fact content_atom method_rule case_experience project_related"),
        enum("browse_category", "genre quote payoff failure dna_case"),
        enum("origin", "manual analysis"),
        "origin<>'analysis' OR source_report_id IS NOT NULL",
        "btrim(title)<>'' AND btrim(body_text)<>''",
        "valid_until>valid_from",
    ),
)
table(
    "knowledge_businesses",
    "org_id:u revision_id:u business_code:t",
    group=2,
    profile="",
    pk=["org_id", "revision_id", "business_code"],
)
table(
    "knowledge_evidence",
    "org_id:u revision_id:u evidence_id:u claim_path:t",
    group=2,
    profile="",
    pk=["org_id", "revision_id", "claim_path", "evidence_id"],
    checks=("btrim(claim_path)<>''",),
)
table(
    "knowledge_relations",
    "from_revision_id:u to_revision_id:u relation_kind:t reason:t? created_by:u",
    group=2,
    unique=("org_id from_revision_id to_revision_id relation_kind",),
    checks=(
        enum("relation_kind", "supports contradicts related derived_from"),
        "from_revision_id<>to_revision_id",
    ),
)
table(
    "review_requests",
    "purpose:t knowledge_revision_id:u? report_id:u? evaluation_id:u? "
    "standard_revision_id:u? input_sha256:h requested_by:u",
    group=2,
    checks=(
        enum("purpose", "knowledge_release report_review evaluation_review standard_approval"),
        xor("knowledge_revision_id", "report_id", "evaluation_id", "standard_revision_id"),
        "(purpose='knowledge_release')=(knowledge_revision_id IS NOT NULL)",
        "(purpose='report_review')=(report_id IS NOT NULL)",
        "(purpose='evaluation_review')=(evaluation_id IS NOT NULL)",
        "(purpose='standard_approval')=(standard_revision_id IS NOT NULL)",
    ),
)
for col in ["knowledge_revision_id", "report_id", "evaluation_id", "standard_revision_id"]:
    index("review_requests", f"org_id purpose {col}", where=f"{col} IS NOT NULL", unique=True)
table(
    "review_heads",
    "org_id:u request_id:u reviewer_kind:t decision_id:u lock_version:b=1 "
    "updated_at:z=CURRENT_TIMESTAMP",
    group=2,
    profile="",
    pk=["org_id", "request_id", "reviewer_kind"],
    mutable=("decision_id", "lock_version", "updated_at"),
    checks=(enum("reviewer_kind", "ai human"),),
)
table(
    "review_decisions",
    "request_id:u reviewer_kind:t reviewer_member_id:u? ai_execution_id:u? "
    "verdict:t reason:t supersedes_decision_id:u? input_sha256:h reviewed_ai_decision_id:u?",
    group=2,
    unique=("org_id id request_id", "org_id id request_id reviewer_kind"),
    checks=(
        enum("reviewer_kind", "ai human"),
        enum("verdict", "approved rejected needs_changes error"),
        (
            "(reviewer_kind='human' AND reviewer_member_id IS NOT NULL AND ai_execution_id IS NULL) OR "
            "(reviewer_kind='ai' AND reviewer_member_id IS NULL AND ai_execution_id IS NOT NULL)"
        ),
        "btrim(reason)<>''",
        "supersedes_decision_id IS DISTINCT FROM id",
    ),
)
index(
    "review_decisions", "org_id request_id ai_execution_id", where="reviewer_kind='ai'", unique=True
)
table(
    "knowledge_publications",
    "knowledge_id:u revision_id:u review_request_id:u ai_decision_id:u "
    "human_decision_id:u published_by:u published_at:z=CURRENT_TIMESTAMP",
    group=2,
    unique=("org_id revision_id", "org_id id knowledge_id"),
)
table(
    "search_documents",
    "publication_id:u revision_id:u document_text:t search_vector:sv "
    "index_config_version:t indexed_at:z=CURRENT_TIMESTAMP",
    group=2,
    mutable=("document_text", "search_vector", "indexed_at"),
    unique=("org_id publication_id index_config_version",),
)
index("search_documents", "search_vector", using="gin")
table(
    "embeddings",
    "search_document_id:u chunk_no:i start_offset:i end_offset:i embedding_model:t "
    "model_version:t dimensions:i embedding:v content_sha256:h",
    group=2,
    mutable=("embedding", "content_sha256"),
    unique=("org_id search_document_id chunk_no embedding_model model_version",),
    checks=(
        "chunk_no>=0",
        "0<=start_offset AND start_offset<end_offset",
        "dimensions>0 AND vector_dims(embedding)=dimensions",
    ),
)

table(
    "intelligence_handoffs",
    "snapshot_id:u snapshot_entry_id:u content_observation_id:u feedback_id:u? "
    "business_code:t business_date:d frozen_by:u idempotency_key:t "
    "schema_version:i=1 manifest_sha256:h body:j",
    group=2,
    unique=("org_id frozen_by idempotency_key",),
    checks=("schema_version=1", "btrim(idempotency_key)<>''"),
)

# Every UUID reference is explicit. Audit target is deliberately a historical label.
TARGETS = {
    "created_by": "members",
    "submitted_by": "members",
    "granted_by": "members",
    "requested_by": "members",
    "execution_authorized_by": "members",
    "authorized_by": "members",
    "uploaded_by": "members",
    "actor_member_id": "members",
    "owner_member_id": "members",
    "assessed_by": "members",
    "author_member_id": "members",
    "frozen_by": "members",
    "reviewer_member_id": "members",
    "published_by": "members",
    "member_id": "members",
    "role_id": "role_definitions",
    "source_id": "sources",
    "raw_asset_id": "raw_assets",
    "parent_raw_asset_id": "raw_assets",
    "parent_artifact_version_id": "artifact_versions",
    "work_id": "works",
    "knowledge_id": "knowledge_items",
    "standard_id": "standards",
    "file_id": "file_objects",
    "cover_file_id": "file_objects",
    "task_id": "tasks",
    "processing_task_id": "tasks",
    "provider_connection_id": "provider_connections",
    "connection_id": "provider_connections",
    "account_id": "external_accounts",
    "content_id": "external_contents",
    "external_content_id": "external_contents",
    "job_id": "collection_jobs",
    "collection_job_id": "collection_jobs",
    "collection_call_id": "collection_calls",
    "plan_id": "collection_plans",
    "attempt_id": "task_attempts",
    "artifact_version_id": "artifact_versions",
    "from_version_id": "artifact_versions",
    "to_version_id": "artifact_versions",
    "artifact_id": "artifacts",
    "snapshot_id": "intelligence_snapshots",
    "feedback_id": "feedback_snapshots",
    "claim_id": "feedback_claims",
    "comment_id": "comment_evidence",
    "snapshot_entry_id": "snapshot_entries",
    "account_observation_id": "account_observations",
    "content_observation_id": "content_observations",
    "input_set_id": "input_sets",
    "knowledge_revision_id": "knowledge_revisions",
    "standard_revision_id": "standard_revisions",
    "prompt_revision_id": "standard_revisions",
    "template_revision_id": "standard_revisions",
    "rubric_revision_id": "standard_revisions",
    "ai_config_revision_id": "ai_config_revisions",
    "config_revision_id": "ai_config_revisions",
    "ai_execution_id": "ai_executions",
    "review_request_id": "review_requests",
    "request_id": "review_requests",
    "review_decision_id": "review_decisions",
    "report_id": "analysis_reports",
    "source_report_id": "analysis_reports",
    "evaluation_id": "quality_evaluations",
    "prediction_id": "predictions",
    "supersedes_prediction_id": "predictions",
    "analysis_run_id": "analysis_runs",
    "evidence_id": "evidence_refs",
    "metric_spec_id": "metric_specs",
    "draft_id": "prediction_drafts",
    "submission_id": "research_submissions",
    "input_manifest_file_id": "file_objects",
    "output_file_id": "file_objects",
    "from_revision_id": "knowledge_revisions",
    "to_revision_id": "knowledge_revisions",
    "revision_id": "knowledge_revisions",
    "publication_id": "knowledge_publications",
    "search_document_id": "search_documents",
    "unit_id": "content_units",
    "primary_unit_id": "content_units",
    "supersedes_decision_id": "review_decisions",
    "reviewed_ai_decision_id": "review_decisions",
    "decision_id": "review_decisions",
    "ai_decision_id": "review_decisions",
    "human_decision_id": "review_decisions",
    "current_revision_id": "knowledge_revisions",
    "current_version_id": "artifact_versions",
    "active_revision_id": "standard_revisions",
    "latest_report_id": "analysis_reports",
    "published_publication_id": "knowledge_publications",
}
COMPOSITE = [
    ("standards", "active_revision_id id", "standard_revisions", "id standard_id"),
    ("works", "latest_report_id id", "analysis_reports", "id work_id"),
    ("artifacts", "primary_unit_id work_id", "content_units", "id work_id"),
    ("artifacts", "current_version_id id", "artifact_versions", "id artifact_id"),
    ("artifact_versions", "artifact_id work_id", "artifacts", "id work_id"),
    ("artifact_version_units", "artifact_version_id work_id", "artifact_versions", "id work_id"),
    ("artifact_version_units", "unit_id work_id", "content_units", "id work_id"),
    ("research_submissions", "artifact_version_id work_id", "artifact_versions", "id work_id"),
    ("input_sets", "unit_id work_id", "content_units", "id work_id"),
    ("input_sets", "artifact_id work_id", "artifacts", "id work_id"),
    ("input_set_items", "input_set_id work_id", "input_sets", "id work_id"),
    ("input_set_items", "artifact_version_id work_id", "artifact_versions", "id work_id"),
    ("analysis_reports", "input_set_id work_id", "input_sets", "id work_id"),
    ("report_units", "report_id work_id", "analysis_reports", "id work_id"),
    ("report_units", "unit_id work_id", "content_units", "id work_id"),
    ("knowledge_items", "current_revision_id id", "knowledge_revisions", "id knowledge_id"),
    ("knowledge_items", "published_publication_id id", "knowledge_publications", "id knowledge_id"),
    (
        "knowledge_publications",
        "revision_id knowledge_id",
        "knowledge_revisions",
        "id knowledge_id",
    ),
    (
        "knowledge_publications",
        "ai_decision_id review_request_id",
        "review_decisions",
        "id request_id",
    ),
    (
        "knowledge_publications",
        "human_decision_id review_request_id",
        "review_decisions",
        "id request_id",
    ),
    (
        "review_heads",
        "decision_id request_id reviewer_kind",
        "review_decisions",
        "id request_id reviewer_kind",
    ),
    ("review_decisions", "reviewed_ai_decision_id request_id", "review_decisions", "id request_id"),
    (
        "review_decisions",
        "supersedes_decision_id request_id reviewer_kind",
        "review_decisions",
        "id request_id reviewer_kind",
    ),
    ("feedback_claim_evidence", "claim_id feedback_id", "feedback_claims", "id feedback_id"),
    (
        "feedback_claim_evidence",
        "feedback_id comment_id",
        "feedback_comments",
        "feedback_id comment_id",
    ),
]
covered = {(t, cols.split()[0]) for t, cols, _, _ in COMPOSITE}
for t in metadata.tables.values():
    for col in t.c:
        if col.name == "org_id":
            fk(t.name, "org_id", "organizations")
        elif (t.name, col.name) not in covered and col.name in TARGETS:
            # audit_events.request_id is text, not a review FK.
            if isinstance(col.type, UUID):
                fk(t.name, col.name, TARGETS[col.name])
        elif col.name.endswith("business_code") or col.name == "business_code":
            fk(t.name, col.name, "business_lines", "code")
        elif col.name == "platform_code":
            fk(t.name, col.name, "platforms", "code")
for args in COMPOSITE:
    fk(*args)

for name, keys in [
    ("grants", "org_id member_id revoked_at"),
    ("audit_events", "org_id occurred_at id"),
    ("audit_events", "org_id target_kind target_id occurred_at"),
    ("file_objects", "org_id sha256"),
    ("tasks", "org_id state created_at id"),
    ("tasks", "state available_at"),
    ("sources", "org_id business_code enabled"),
    ("collection_plans", "org_id source_id enabled"),
    ("collection_jobs", "org_id source_id business_date created_at id"),
    ("raw_assets", "org_id sha256"),
    ("account_observations", "org_id account_id observed_at id"),
    ("content_observations", "org_id content_id observed_at id"),
    ("intelligence_snapshots", "org_id business_code business_date view_kind created_at id"),
    ("comment_evidence", "org_id content_id captured_at id"),
    ("works", "org_id business_code created_at id"),
    ("research_submissions", "org_id work_id import_key created_at id"),
    ("analysis_runs", "org_id input_set_id created_at id"),
    ("quality_evaluations", "org_id input_set_id created_at id"),
    ("knowledge_businesses", "business_code org_id revision_id"),
    ("review_decisions", "org_id request_id created_at id"),
]:
    index(name, keys)

# S05.2 service tables: separate from the immutable B1 inventory (17/18/35).
sa.Table(
    "auth_sessions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("org_id", UUID(as_uuid=True), nullable=False),
    sa.Column("member_id", UUID(as_uuid=True), nullable=False),
    sa.Column("token_hash", sa.CHAR(64), nullable=False, unique=True),
    sa.Column("credential_hash", sa.CHAR(64), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["org_id", "member_id"],
        ["members.org_id", "members.id"],
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("expires_at>created_at"),
    sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$' AND credential_hash ~ '^[0-9a-f]{64}$'"),
)
sa.Table(
    "auth_rate_limits",
    metadata,
    sa.Column("bucket", sa.CHAR(64), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.CheckConstraint("attempts>0"),
)
sa.Table(
    "http_receipts",
    metadata,
    sa.Column("org_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("member_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("operation", sa.Text(), primary_key=True),
    sa.Column("key", UUID(as_uuid=True), primary_key=True),
    sa.Column("input_sha256", sa.CHAR(64), nullable=False),
    sa.Column("response", JSONB(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.ForeignKeyConstraint(
        ["org_id", "member_id"],
        ["members.org_id", "members.id"],
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$' AND btrim(operation)<>''"),
    sa.CheckConstraint("jsonb_typeof(response)='object'"),
)
sa.Index(
    "ix_auth_sessions_member",
    metadata.tables["auth_sessions"].c.org_id,
    metadata.tables["auth_sessions"].c.member_id,
)

# S05.3 immutable intake scope; not part of the historic B1 table groups.
sa.Table(
    "file_intakes",
    metadata,
    sa.Column("org_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("file_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("work_id", UUID(as_uuid=True), nullable=False),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("origin_kind", sa.Text(), nullable=False),
    sa.Column("source_url", sa.Text()),
    sa.ForeignKeyConstraint(
        ["org_id", "file_id"],
        ["file_objects.org_id", "file_objects.id"],
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["org_id", "work_id"],
        ["works.org_id", "works.id"],
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["org_id", "created_by"],
        ["members.org_id", "members.id"],
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("origin_kind IN ('upload','external')"),
    sa.CheckConstraint("(origin_kind='external')=(source_url IS NOT NULL)"),
)
sa.Index(
    "ix_file_intakes_work",
    metadata.tables["file_intakes"].c.org_id,
    metadata.tables["file_intakes"].c.work_id,
)

sa.ForeignKeyConstraint(["org_id", "handoff_id"], ["intelligence_handoffs.org_id", "intelligence_handoffs.id"], table=metadata.tables["research_submissions"], name="fk_submission_handoff", deferrable=True, initially="DEFERRED", ondelete="RESTRICT")
