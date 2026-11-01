"""Explicit administrator read-only personal space; ordinary lists stay personal."""

from app.accounts.contracts import UserView
from app.contracts.models import Contract
from app.topics.contracts import Business, SparkView, TopicView


class PersonalSpaceQuery(Contract):
    business_code: Business


class PersonalSpaceView(Contract):
    member: UserView
    sparks: list[SparkView]
    topics: list[TopicView]
