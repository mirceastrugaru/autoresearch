"""Pydantic models for the Autoresearch API."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


# ── Sessions ────────────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    thesis: str


class SessionSummary(BaseModel):
    id: str
    thesis: str
    stage: str
    updatedAt: str


class SessionConfig(BaseModel):
    thesis: str
    directions: list[DirectionItem]
    rubric: Optional[RubricData]
    rounds: int
    workersPerRound: int
    costCap: Optional[float]


class SessionFull(BaseModel):
    id: str
    thesis: str
    stage: str
    config: Optional[SessionConfig]
    run: Optional[dict]
    verdict: Optional[dict]
    createdAt: str
    updatedAt: str


class SessionList(BaseModel):
    items: list[SessionSummary]
    nextCursor: Optional[str]


# ── Directions ──────────────────────────────────────────────────────────────


class DirectionItem(BaseModel):
    id: str
    stance: str
    text: str
    status: str = "queued"
    score: Optional[float] = None
    coverage: int = 0


class DirectionCreate(BaseModel):
    stance: str
    text: str


class DirectionUpdate(BaseModel):
    text: Optional[str] = None
    stance: Optional[str] = None


# ── Rubric ──────────────────────────────────────────────────────────────────


class RubricData(BaseModel):
    hardGates: list[str]
    softGates: dict[str, str]


class RubricUpdate(BaseModel):
    hardGates: Optional[list[str]] = None
    softGates: Optional[dict[str, str]] = None


# ── Config updates ──────────────────────────────────────────────────────────


class ConfigUpdate(BaseModel):
    thesis: Optional[str] = None
    rounds: Optional[int] = None
    workersPerRound: Optional[int] = None
    costCap: Optional[float] = None


# ── Estimates ───────────────────────────────────────────────────────────────


class EstimateResponse(BaseModel):
    estimatedCost: float
    estimatedTokens: int
    estimatedDurationSec: int


# ── Verdict ─────────────────────────────────────────────────────────────────


class VerdictResponse(BaseModel):
    leaning: str
    tension: dict[str, int]
    headline: str
    subtitle: str
    stats: dict


# ── Writeups ────────────────────────────────────────────────────────────────


class WriteupSummary(BaseModel):
    id: str
    workerId: str
    round: int
    stance: str
    dir: str
    score: float
    status: str
    excerpt: str


class WriteupDetail(BaseModel):
    id: str
    workerId: str
    round: int
    stance: str
    dir: str
    score: float
    status: str
    content: str
    rubricBreakdown: Optional[dict] = None


# ── Activity ────────────────────────────────────────────────────────────────


class ActivityEntry(BaseModel):
    t: str
    who: str
    stance: Optional[str] = None
    msg: str


# ── Burndown ────────────────────────────────────────────────────────────────


class BurndownRound(BaseModel):
    r: int
    covered: int
    inProgress: int
    queued: int
    proposed: int
    isNow: Optional[bool] = None
    projected: Optional[bool] = None


class BurndownResponse(BaseModel):
    rounds: list[BurndownRound]
    velocity: float
    projection: str


# ── Chat ────────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    text: str


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    stage: str
    text: str
    toolCalls: Optional[list[dict]] = None
    createdAt: str


# Forward references
SessionConfig.model_rebuild()
SessionFull.model_rebuild()
