"""Rebuild S04 snapshots during initial development only; never run after release."""

from pathlib import Path

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, DropConstraint

from app.core.models import TABLE_GROUPS, metadata
from migrations.guards import build
from migrations.operations import SQL as operations
from migrations.relationships import build as relationships

ROOT = Path(__file__).parent
if (ROOT / "manifest.json").exists():
    raise RuntimeError(
        "S04 migration is released; add an incremental revision, never rewrite history."
    )
DIALECT = postgresql.dialect()
for number, names in enumerate(TABLE_GROUPS, 1):
    statements = []
    for name in names:
        obj = metadata.tables[name]
        statements.append(
            str(CreateTable(obj, include_foreign_key_constraints=[]).compile(dialect=DIALECT)) + ";"
        )
        for idx in sorted(obj.indexes, key=lambda i: i.name):
            statements.append(str(CreateIndex(idx).compile(dialect=DIALECT)) + ";")
    if number == 1:
        statements.insert(0, "CREATE EXTENSION IF NOT EXISTS vector;")
        statements.extend(
            [
                "INSERT INTO business_lines(code,name) VALUES ('motion_comic','AI漫剧'),('story_short','故事短片'),('ecommerce_video','电商短视频');",
                "INSERT INTO platforms(code,name) VALUES ('douyin','抖音');",
            ]
        )
    (ROOT / "sql" / f"000{number}_up.sql").write_text("\n".join(statements))
    (ROOT / "sql" / f"000{number}_down.sql").write_text(
        "\n".join(f"DROP TABLE {n};" for n in reversed(names))
    )
constraints = [
    c
    for t in metadata.tables.values()
    for c in t.constraints
    if isinstance(c, ForeignKeyConstraint)
]
(ROOT / "sql" / "0004_up.sql").write_text(
    "\n".join(str(AddConstraint(c).compile(dialect=DIALECT)) + ";" for c in constraints)
    + "\n"
    + build()
    + "\n"
    + relationships(metadata.tables)
    + "\n"
    + operations
    + """
-- Validate existing tenants as well as rows written after guard installation.
CREATE TEMP TABLE cip_migration_check(org_id uuid NOT NULL) ON COMMIT DROP;
CREATE CONSTRAINT TRIGGER existing_integrity AFTER INSERT ON cip_migration_check
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_validate();
CREATE CONSTRAINT TRIGGER existing_relationships AFTER INSERT ON cip_migration_check
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_relationships();
INSERT INTO cip_migration_check SELECT id FROM organizations;
SET CONSTRAINTS ALL IMMEDIATE;
"""
)
(ROOT / "sql" / "0004_down.sql").write_text(
    "\n".join(
        f"DROP TRIGGER {trg} ON {t.name};"
        for t in metadata.tables.values()
        for trg in [
            "a0_tenant_lock",
            "a_parent",
            "a_new_seal",
            "b_pointer",
            "b_task",
            "b_runtime",
            "b_identity",
            "z_authz",
            "z_immutable",
            "zz_integrity",
            "zz_relationships",
        ]
        if (
            trg == "z_immutable"
            or (trg in ["zz_integrity", "zz_relationships", "a0_tenant_lock"] and "org_id" in t.c)
            or (
                trg == "b_pointer"
                and t.name in ["standards", "works", "knowledge_items", "artifacts"]
            )
            or (
                trg == "a_parent"
                and t.name in __import__("migrations.guards", fromlist=["CHILDREN"]).CHILDREN
            )
            or (trg == "a_new_seal" and "sealed_at" in t.c)
            or (trg == "b_task" and t.name == "tasks")
            or (
                trg == "b_runtime"
                and t.name in ["task_attempts", "collection_calls", "ai_executions"]
            )
            or (
                trg == "b_identity"
                and t.name
                in [
                    "organizations",
                    "grants",
                    "raw_asset_events",
                    "predictions",
                    "prediction_events",
                    "review_decisions",
                    "review_heads",
                    "knowledge_publications",
                ]
            )
            or (
                trg == "z_authz"
                and t.name in ["grants", "members", "role_actions", "raw_asset_events"]
            )
        )
    )
    + "\n"
    + "\n".join(
        f"DROP FUNCTION {sig};"
        for sig in [
            "cip_finish_task(uuid,uuid,uuid,uuid,bigint,text,text,text)",
            "cip_claim_task(uuid,uuid,bigint,integer)",
            "cip_relationships()",
            "cip_input_contains(uuid,uuid,uuid)",
            "cip_graph_edges(uuid)",
            "cip_write_lock()",
            "cip_pointer_guard()",
            "cip_parent_open()",
            "cip_immutable()",
            "cip_seal(text,uuid,uuid,text)",
            "cip_task_guard()",
            "cip_new_seal()",
            "cip_runtime_guard()",
            "cip_identity_guard()",
            "cip_authz_changed()",
            "cip_validate()",
        ]
    )
    + "\n"
    + "\n".join(
        str(DropConstraint(c).compile(dialect=DIALECT)) + ";" for c in reversed(constraints)
    )
)
for number in range(1, 5):
    revision = f"000{number}_b1"
    previous = repr(f"000{number - 1}_b1") if number > 1 else "None"
    (
        ROOT / "versions" / f"{revision}.py"
    ).write_text(f'''"""S04 frozen B1 migration {number}; SQL is immutable after release."""
from pathlib import Path
from alembic import op
revision = {revision!r}
down_revision = {previous}
branch_labels = None
depends_on = None


def apply(direction):
    sql = (Path(__file__).parents[1] / 'sql' / f'000{number}_{{direction}}.sql').read_text()
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply('up')


def downgrade():
    apply('down')
''')
