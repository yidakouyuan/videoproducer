"""
视频拼接模块请求与响应 Schema。

对应接口：
  POST /video/stitch
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StitchRequest(BaseModel):
    video_paths: list[str] = Field(
        ...,
        min_length=2,
        max_length=200,
        description="按顺序排列的本地 MP4 路径列表（至少 2 个，最多 200 个）。路径为服务端本地路径。",
    )
    output_name: Optional[str] = Field(
        None,
        description="输出文件名（不含扩展名），不传则自动生成。",
    )
    reencode: bool = Field(
        False,
        description=(
            "false（默认）= 流复制（-c copy），极快，要求各片段编码参数一致；"
            "true = 强制转码到 1920x1080 H.264，保证编码兼容性，速度较慢。"
        ),
    )


class StitchData(BaseModel):
    local_video_path: str
    clip_count: int
