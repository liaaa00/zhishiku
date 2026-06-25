from typing import List, Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    group_ids: List[str] = []


class UserUpdate(BaseModel):
    username: str
    is_admin: bool = False
    is_active: bool = True
    group_ids: List[str] = []


class UserPasswordReset(BaseModel):
    password: str


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserGroupsUpdate(BaseModel):
    group_ids: List[str] = []
    is_admin: Optional[bool] = None


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    name: str


class DocumentPermissionUpdate(BaseModel):
    group_ids: List[str]


class ChunkUpdate(BaseModel):
    content: str


class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    top_k: int = 5


class FeedbackCreate(BaseModel):
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    rating: Optional[str] = None
    category: Optional[str] = None
    feedback_category: Optional[str] = None
    content: str


class FeedbackReview(BaseModel):
    status: str = "reviewed"
    review_note: str = ""
    admin_note: str = ""


class ModelConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    embedding_provider: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    reranker_enabled: bool = False
    reranker_model: str = ""
    reranker_max_candidates: int = 24
