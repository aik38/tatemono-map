from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BuildingBase(BaseModel):
    name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    lat: float
    lng: float
    building_type: str | None = None
    floors: int | None = None
    year_built: int | None = None
    source: str | None = None

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, value: float) -> float:
        if value < -90 or value > 90:
            raise ValueError("lat must be between -90 and 90")
        return value

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, value: float) -> float:
        if value < -180 or value > 180:
            raise ValueError("lng must be between -180 and 180")
        return value


class BuildingCreate(BuildingBase):
    pass


class BuildingUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    building_type: str | None = None
    floors: int | None = None
    year_built: int | None = None
    source: str | None = None

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < -90 or value > 90:
            raise ValueError("lat must be between -90 and 90")
        return value

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < -180 or value > 180:
            raise ValueError("lng must be between -180 and 180")
        return value


class BuildingRead(BuildingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
