from fastapi import FastAPI

from app.api.health import router as health_router
from app.collection.http import mount as mount_collection
from app.intelligence.http import mount as mount_intelligence
from app.knowledge.http import mount as mount_knowledge
from app.research.http import mount as mount_research
from app.security.http import mount
from app.storage.http import mount as mount_storage

app = FastAPI(title="内容智库 API", version="0.1.0")
app.include_router(health_router, prefix="/api")

mount(app)

mount_storage(app)

mount_collection(app)

mount_intelligence(app)


mount_research(app)


mount_knowledge(app)
