from __future__ import annotations

from pydantic import Field

from app.schemas.common_schema import FlexibleModel


class SchoolEnvironmentCandidate(FlexibleModel):
    id: str
    name: str
    primaryType: str | None = None
    types: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    distanceMeters: float
    distanceLabel: str


class SchoolEnvironmentCurationRequest(FlexibleModel):
    schoolName: str | None = None
    schoolAddress: str | None = None
    latitude: float
    longitude: float
    radiusMeters: int = 5000
    candidates: list[SchoolEnvironmentCandidate] = Field(default_factory=list)
    maxPlaces: int = 18
    maxPlacesPerCategory: int = 3
    minCategories: int = 4


class SchoolEnvironmentPlace(FlexibleModel):
    id: str
    categoryId: str
    category: str
    colorKey: str = "gray"
    relevanceNote: str
    relevanceScore: int = 70


class SchoolEnvironmentCurationResponse(FlexibleModel):
    summary: str
    places: list[SchoolEnvironmentPlace] = Field(default_factory=list)
