"""
Domain models — strictly following the interface document (接口文档.txt).
All types are plain dataclasses; Pydantic schemas live in app/schemas/.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# 2.1 通用基础枚举
# ---------------------------------------------------------------------------

Platform = Literal[
    "douyin",
    "xiaohongshu",
    "weibo",
    "bilibili",
    "youtube",
    "other",
]

SourceType = Literal[
    "post",
    "video",
    "note",
    "article",
    "image_post",
    "other",
]

MediaType = Literal[
    "video",
    "audio",
    "image",
    "text",
    "other",
]

AnalysisType = Literal[
    "video_understanding",
    "transcription",
    "image_understanding",
    "ocr",
    "music_identification",
    "other",
]

JobStatus = Literal[
    "queued",
    "running",
    "done",
    "failed",
    "partial",
    "cancelled",
]

SourceQuality = Literal[
    "high",
    "medium",
    "low",
]

# ---------------------------------------------------------------------------
# 2.2 用户任务相关
# ---------------------------------------------------------------------------


@dataclass
class CreativeBrief:
    user_query: str
    theme: Optional[str] = None
    audience: Optional[str] = None
    duration_sec: Optional[int] = None
    style: Optional[str] = None
    lang: str = "zh"
    publish_required: bool = False
    constraints: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputMaterial:
    material_type: MediaType | Literal["link"]
    text: Optional[str] = None
    source_ref: Optional["ContentRef"] = None
    media_id: Optional[str] = None
    url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputMaterialSet:
    materials: List[InputMaterial] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 2.3 平台内容引用相关
# ---------------------------------------------------------------------------


@dataclass
class ContentRef:
    platform: Platform
    source_type: SourceType
    source_id: str
    source_url: str
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    title: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Stats:
    digg: Optional[int] = None
    collect: Optional[int] = None
    comment: Optional[int] = None
    share: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoverImage:
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class AuthorInfo:
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoCandidate:
    content_ref: ContentRef
    title: str
    stats: Stats = field(default_factory=Stats)
    tags: List[str] = field(default_factory=list)
    cover_image: Optional[CoverImage] = None
    author: Optional[AuthorInfo] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2.4 媒体解析与缓存相关
# ---------------------------------------------------------------------------


@dataclass
class ResolvedMediaRef:
    content_ref: ContentRef
    media_type: MediaType
    media_url: Optional[str] = None
    downloadable: bool = False
    mime_type: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageInfo:
    local_path: Optional[str] = None
    object_url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredMedia:
    media_id: str
    content_ref: ContentRef
    media_type: MediaType
    storage: StorageInfo
    duration_sec: Optional[float] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2.5 分析结果相关
# ---------------------------------------------------------------------------


@dataclass
class ShotSegment:
    start_sec: float
    end_sec: float
    shot_type: Optional[str] = None
    visual: Optional[str] = None
    text_overlay: Optional[str] = None
    camera_motion: Optional[str] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class VideoBreakdown:
    structure: Dict[str, Any] = field(default_factory=dict)
    editing_style: Dict[str, Any] = field(default_factory=dict)
    shots: List[ShotSegment] = field(default_factory=list)
    audio: Dict[str, Any] = field(default_factory=dict)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    # 100-150 中文字概述（hook + 主体 + 卖点），用于下游 writer 渐进披露：
    # research_douyin.json 索引文件只放 summary，不放完整 video_breakdown，
    # writer 先扫 summary 决定是否 read 完整 detail 文件。
    summary: str = ""


@dataclass
class TranscriptHighlight:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class TranscriptResult:
    transcript: str
    highlights: List[TranscriptHighlight] = field(default_factory=list)
    confidence: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompressedSummary:
    summary_text: str
    key_points: List[str] = field(default_factory=list)
    fit_score_hint: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2.6 证据相关
# ---------------------------------------------------------------------------


@dataclass
class WebEvidence:
    evidence_id: str
    title: str
    url: str
    snippet: Optional[str] = None
    claim: Optional[str] = None
    extracted_text: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[str] = None
    source_quality: Optional[SourceQuality] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2.7 GraphRAG / Script Pack 相关
# ---------------------------------------------------------------------------


@dataclass
class TagCard:
    tag: str
    summary_1_2_sentences: str


@dataclass
class FindingItem:
    summary: str
    explanation: str


@dataclass
class CommunityReport:
    community_id: str
    title: str
    summary: Optional[str] = None
    findings: List[FindingItem] = field(default_factory=list)
    rating: Optional[float] = None
    report_source: str = "template"  # "template" | "llm"
    member_tags: List[str] = field(default_factory=list)


@dataclass
class EvidencePack:
    tag: str
    top_titles: List[str] = field(default_factory=list)
    stats_snapshot: Dict[str, Any] = field(default_factory=dict)
    cooccur_topk: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScriptPack:
    canonical_topic: str
    tag_card: Optional[TagCard] = None
    community_reports: List[CommunityReport] = field(default_factory=list)
    evidence_packs: List[EvidencePack] = field(default_factory=list)
    search_seeds: Dict[str, List[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2.8 最终收敛对象
# ---------------------------------------------------------------------------


@dataclass
class SelectedVideoEvidence:
    media_id: str
    content_ref: ContentRef
    video_breakdown: Optional[VideoBreakdown] = None
    transcript_result: Optional[TranscriptResult] = None
    compressed_summary: Optional[CompressedSummary] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceBundle:
    creative_brief: CreativeBrief
    script_pack: ScriptPack
    selected_videos: List[SelectedVideoEvidence] = field(default_factory=list)
    selected_web_evidence: List[WebEvidence] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 异步 Job：视频分析
# ---------------------------------------------------------------------------


@dataclass
class VideoAnalysisJob:
    """视频分析异步任务记录。

    生命周期：queued → running → done / failed
    """

    job_id: str
    media_id: str
    input_url: Optional[str]
    analysis_profile: str
    lang: str
    output_schema_version: str
    status: JobStatus
    source_quality: Optional[SourceQuality] = None
    analysis_confidence: Optional[float] = None
    video_breakdown: Optional[VideoBreakdown] = None
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 异步 Job：转写
# ---------------------------------------------------------------------------


@dataclass
class TranscribeJob:
    """转写异步任务记录。

    生命周期：queued → running → done / failed
    """

    job_id: str
    media_id: str
    provider_name: str   # "openai" / "gemini" 等，由调用方指定
    lang: str
    mode: str            # "highlights" / "full"
    status: JobStatus
    transcript: Optional[str] = None
    highlights: List[TranscriptHighlight] = field(default_factory=list)
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 异步 Job：视频生成（Seedance）
# ---------------------------------------------------------------------------


@dataclass
class VideoGenerateJob:
    """视频生成异步任务记录。

    生命周期：queued → running → done / failed

    first_frame_path: 首帧参考图（URL 或本地路径）。
      - 传入时使用 i2v 模式（provider 支持时把图作为生成首帧）。
      - 不传时为纯 t2v。
    """

    job_id: str
    prompt: str
    status: JobStatus
    duration: int = 6                          # 视频时长（秒）
    first_frame_path: Optional[str] = None     # 首帧参考图（i2v 模式）
    model: Optional[str] = None                # 实际使用的模型名
    task_id: Optional[str] = None              # 上游平台返回的任务 ID
    local_video_path: Optional[str] = None     # 下载后的本地 MP4 路径
    manifest_path: Optional[str] = None        # 元数据 JSON 路径
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 异步 Job：图片生成
# ---------------------------------------------------------------------------


@dataclass
class ImageGenerateJob:
    """图片生成异步任务记录。

    生命周期：queued → running → done / failed

    style_reference_path: 风格参考图（URL 或本地路径）。
      - 传入时使用图生图/风格迁移模式（provider 支持时）；
      - 不传时为纯文生图。
    """

    job_id: str
    prompt: str
    status: JobStatus
    style_reference_path: Optional[str] = None   # 风格参考图路径或 URL（可选）
    model: Optional[str] = None                  # 实际使用的模型名
    task_id: Optional[str] = None                # 上游平台返回的任务 ID
    local_image_path: Optional[str] = None       # 下载后的本地图片路径
    image_url: Optional[str] = None              # 上游返回的图片 URL
    manifest_path: Optional[str] = None          # 元数据 JSON 路径
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
