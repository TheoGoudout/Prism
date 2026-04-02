import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from app.models.common import get_datetime_utc
from app.models.user import User


class WorkspaceRole(str, Enum):
    owner = "owner"
    admin = "admin"
    viewer = "viewer"


# ---------------------------------------------------------------------------
# Database models
# ---------------------------------------------------------------------------


class Workspace(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(unique=True, index=True, max_length=100)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    members: list["WorkspaceMember"] = Relationship(
        back_populates="workspace", cascade_delete=True
    )


class WorkspaceMember(SQLModel, table=True):
    __tablename__ = "workspacemember"

    workspace_id: uuid.UUID = Field(
        foreign_key="workspace.id", primary_key=True, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE"
    )
    role: WorkspaceRole = Field(default=WorkspaceRole.viewer)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    workspace: Workspace | None = Relationship(back_populates="members")
    user: User | None = Relationship(back_populates="workspace_memberships")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class WorkspaceCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)


class WorkspaceUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)


class WorkspacePublic(SQLModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime | None = None
    # Role of the requesting user in this workspace
    role: WorkspaceRole


class WorkspacesPublic(SQLModel):
    data: list[WorkspacePublic]
    count: int


class WorkspaceMemberPublic(SQLModel):
    user_id: uuid.UUID
    role: WorkspaceRole
    created_at: datetime | None = None
    # Flattened user info for convenience
    user_email: str
    user_full_name: str | None = None


class WorkspaceMembersPublic(SQLModel):
    data: list[WorkspaceMemberPublic]
    count: int


class WorkspaceMemberAdd(SQLModel):
    user_id: uuid.UUID
    role: WorkspaceRole = WorkspaceRole.viewer


class WorkspaceMemberUpdate(SQLModel):
    role: WorkspaceRole
