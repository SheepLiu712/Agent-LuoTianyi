from fastapi import File, Form, UploadFile
from pydantic import BaseModel


class ChatRequest(BaseModel):
    text: str
    username: str
    token: str


class HistoryRequest(BaseModel):
    username: str
    token: str | None = None
    count: int = 10
    end_index: int = -1


class HistoryQuery(BaseModel):
    username: str
    count: int = 10
    end_index: int = -1


class LoginRequest(BaseModel):
    username: str
    password: str
    request_token: bool = False


class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str


class ResetAccountRequest(BaseModel):
    """通过邀请码重置用户名和密码"""

    invite_code: str
    new_username: str
    new_password: str


class AutoLoginRequest(BaseModel):
    username: str
    token: str


class PreferenceGetRequest(BaseModel):
    username: str
    token: str


class PreferenceOverwriteRequest(BaseModel):
    username: str
    token: str
    preferences: dict


class DynamicListRequest(BaseModel):
    username: str
    token: str | None = None
    limit: int = 20
    cursor: str | None = None


class DynamicListQuery(BaseModel):
    username: str
    limit: int = 20
    cursor: str | None = None


class DynamicCreateRequest(BaseModel):
    username: str
    token: str
    content: str


class DynamicCommentListRequest(BaseModel):
    username: str
    token: str | None = None
    limit: int = 100
    cursor: str | None = None


class DynamicCommentListQuery(BaseModel):
    username: str
    limit: int = 100
    cursor: str | None = None


class DynamicCommentCreateRequest(BaseModel):
    username: str
    token: str
    content: str
    parent_comment_id: str | None = None


class DynamicUnreadRequest(BaseModel):
    username: str
    token: str | None = None


class DynamicUnreadQuery(BaseModel):
    username: str


class DynamicReadMarkRequest(BaseModel):
    username: str
    token: str


class PictureChatRequest:
    def __init__(
        self,
        username: str = Form(...),
        token: str = Form(...),
        image: UploadFile = File(...),
        image_client_path: str = Form(None),
    ):
        self.username = username
        self.token = token
        self.image = image
        self.image_client_path = image_client_path


class ImageRequest(BaseModel):
    username: str
    token: str
    uuid: str
    image_client_path: str = None
