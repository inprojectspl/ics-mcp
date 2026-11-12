"""Argument models of the micro-application tools (ICS `ics.microapp/v1alpha1`)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

MicroAppAction = Literal["enable", "suspend", "sleep", "restart"]
ContractSection = Literal[
    "manifest_schema",
    "sdk_types",
    "browser_sdk",
    "template",
    "limits",
    "errors",
    "management_api",
    "procedure",
]

IdempotencyKeyArg = Annotated[
    str | None,
    Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Stable key; repeat it after a lost response. Default: derived from the request.",
    ),
]


class PackageFile(BaseModel):
    """One file of a micro-application package."""

    path: str = Field(max_length=200)
    content_text: str | None = Field(None, max_length=5 * 1024 * 1024)
    content_base64: str | None = None
    content_path: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> PackageFile:
        given = [
            v for v in (self.content_text, self.content_base64, self.content_path) if v is not None
        ]
        if len(given) != 1:
            raise ValueError(
                f"{self.path}: give exactly one of content_text, content_base64 or content_path"
            )
        return self
