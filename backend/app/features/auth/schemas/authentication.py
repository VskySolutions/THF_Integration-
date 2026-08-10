from pydantic import BaseModel


class AuthenticationStatus(BaseModel):
    authenticated: bool
