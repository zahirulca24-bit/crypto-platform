from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
class BotIntent(str, Enum): START="start"; PAUSE="pause"; RESUME="resume"; STOP="stop"
class BotStatus(str, Enum): STOPPED="stopped"; RUNNING="running"; PAUSED="paused"
class BotCommandRequest(BaseModel): intent: BotIntent; idempotency_key: str|None=None
class BotCommand(BaseModel):
 id: UUID=Field(default_factory=uuid4); intent: BotIntent; idempotency_key:str; processed_at:datetime|None=None; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class BotRuntimeState(BaseModel):
 bot_id:str="demo-bot"; status:BotStatus=BotStatus.STOPPED; supervisor_id:str|None=None; worker_id:str|None=None; heartbeat_at:datetime|None=None; updated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class JournalEvent(BaseModel):
 id:UUID=Field(default_factory=uuid4); event_type:str; payload:dict[str,Any]=Field(default_factory=dict); created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
