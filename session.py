from fastapi import Request, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel

class UserSession(BaseModel):
    user_id: int
    nickname: str

def get_session_data(request: Request) -> Optional[UserSession]:
    session_id = request.cookies.get("session_id")
    if session_id is None:
        raise HTTPException(status_code=401, detail="No session_id in cookies")

    user_id = request.cookies.get("user_id")
    nickname = request.cookies.get("nickname")
    if user_id is None or nickname is None:
        raise HTTPException(status_code=401, detail="Session data is incomplete")

    return UserSession(user_id=int(user_id), nickname=nickname)
