import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

basic = HTTPBasic(auto_error=False)


def require_admin(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    """HTTP Basic auth: any username, password = ADMIN_TOKEN.

    If ADMIN_TOKEN is unset, access is open locally but refused on Vercel.
    """
    token = os.getenv("ADMIN_TOKEN")
    if not token:
        if os.getenv("VERCEL"):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_TOKEN not configured")
        return
    if creds and secrets.compare_digest(creds.password, token):
        return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Unauthorized", headers={"WWW-Authenticate": "Basic"}
    )
