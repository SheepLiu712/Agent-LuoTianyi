
from pydantic import BaseModel
class ChatRequest(BaseModel):
    text: str
    username: str
    token: str

class HistoryRequest(BaseModel):
    username: str
    token: str
    count: int = 10
    end_index: int = -1

class ChatResponse(BaseModel):
    uuid: str
    text: str
    audio: str | None = None
    expression: str | None = None
    is_final_package: bool = True

class LoginRequest(BaseModel):
    username: str
    password: str
    request_token: bool = False

class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str

class AutoLoginRequest(BaseModel):
    username: str
    token: str

from fastapi import Form, File, UploadFile
class PictureChatRequest:
    def __init__(
        self,
        username: str = Form(...),
        token: str = Form(...),
        image: UploadFile = File(...),
        image_client_path: str = Form(None)
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