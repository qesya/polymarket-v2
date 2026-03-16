from __future__ import annotations
from typing import List
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from fastapi import Request


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql://trader:changeme@localhost:5432/polymarket"
    prometheus_url: str = "http://localhost:8001"
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:4173", "http://localhost:3000"]


def get_pg(request: Request):
    return request.app.state.pg_pool


def get_redis(request: Request):
    return request.app.state.redis


def get_ws_manager(request: Request):
    return request.app.state.ws_manager


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
