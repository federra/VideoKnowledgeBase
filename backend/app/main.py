from fastapi import FastAPI

from app.accounts.http import OPERATIONS as ACCOUNT_OPERATIONS
from app.accounts.http import mount as mount_accounts
from app.accounts.personal_http import OPERATIONS as PERSONAL_OPERATIONS
from app.accounts.personal_http import mount as mount_personal
from app.api.health import router as health_router
from app.collection.http import mount as mount_collection
from app.contracts.api import OPERATIONS, add_operation
from app.intelligence.creator_http import mount as mount_creators
from app.intelligence.http import mount as mount_intelligence
from app.intelligence.refresh_http import mount as mount_refresh
from app.knowledge.http import mount as mount_knowledge
from app.knowledge.retention import lifespan
from app.model_config.http import OPERATIONS as MODEL_OPERATIONS
from app.model_config.http import mount as mount_models
from app.research.http import mount as mount_research
from app.security.http import mount
from app.storage.http import mount as mount_storage
from app.topics.http import OPERATIONS as TOPIC_OPERATIONS
from app.topics.http import mount as mount_topics
from app.topics.score_http import OPERATIONS as SCORE_OPERATIONS
from app.topics.score_http import mount as mount_topic_scores

app = FastAPI(title="内容智库 API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router, prefix="/api")

mount(app)

mount_storage(app)

mount_collection(app)

mount_intelligence(app)


mount_research(app)


mount_knowledge(app)

mount_refresh(app)
mount_creators(app)

# Register implemented topic/model contracts in both design and runtime inventories.
for spec in [
    *MODEL_OPERATIONS,
    *TOPIC_OPERATIONS,
    *SCORE_OPERATIONS,
    *ACCOUNT_OPERATIONS,
    *PERSONAL_OPERATIONS,
]:
    if not any(old.name == spec.name for old in OPERATIONS):
        OPERATIONS.append(spec)
        add_operation(spec)
mount_models(app)
mount_topics(app)
mount_topic_scores(app)

mount_accounts(app)

mount_personal(app)
