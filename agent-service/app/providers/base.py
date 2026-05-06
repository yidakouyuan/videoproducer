"""
Provider 接口定义（typing.Protocol）。

原则：
- service 层只依赖这里的 Protocol，不直接 import 具体实现。
- 换真实实现时只需替换依赖注入处的实例，service / route 代码不动。
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.domain.models import ImageGenerateJob, ResolvedMediaRef, ScriptPack, StoredMedia, TranscribeJob, VideoAnalysisJob


@runtime_checkable
class ScriptPackProvider(Protocol):
    """GraphRAG / Script Pack 查询 provider 接口。

    真实实现（如 Neo4jScriptPackProvider、GraphRAGHttpProvider）
    只要实现此方法签名即可，无需继承。
    """

    async def get_script_pack(
        self,
        tag: str,
        top_k_communities: int,
        top_k_cooccur: int,
        lang: str,
        version: str,
    ) -> ScriptPack:
        """
        根据 tag 查询 ScriptPack。

        Args:
            tag: 目标标签，如 "清迈旅行"
            top_k_communities: 返回社区报告数量上限
            top_k_cooccur: 共现标签数量上限
            lang: 语言代码，如 "zh"
            version: GraphRAG 数据版本，如 "latest"

        Returns:
            ScriptPack domain 对象

        Raises:
            app.infra.exceptions.NotFoundError: tag 不存在于知识库
            app.infra.exceptions.ProviderError: 底层查询服务不可用
        """
        ...


# ---------------------------------------------------------------------------
# 媒体 Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class MediaProvider(Protocol):
    """媒体解析、下载、存储管理的 provider 接口。

    真实实现可按职责拆分为：
      - DouyinVideoResolver（负责 resolve）
      - VideoDownloader + ObjectStorage（负责 fetch）
      - MediaRepository / DB（负责 CRUD）
    MVP 阶段 Mock 将三者合并到一个类。
    """

    async def resolve_video(
        self,
        platform: str,
        aweme_id: str,
        share_url: str,
    ) -> ResolvedMediaRef:
        """解析平台视频，返回可下载的媒体引用。

        Raises:
            app.infra.exceptions.ProviderError: 解析失败（网络、反爬等）
            app.infra.exceptions.NotFoundError: 视频已删除或不存在
        """
        ...

    async def fetch_video(
        self,
        resolved: ResolvedMediaRef,
    ) -> StoredMedia:
        """下载并缓存视频，生成系统内部 media_id。

        Raises:
            app.infra.exceptions.ProviderError: 下载或存储失败
            app.infra.exceptions.InvalidInputError: resolved.downloadable=False
        """
        ...

    async def get_media(self, media_id: str) -> Optional[StoredMedia]:
        """按 media_id 查询已缓存的媒体。返回 None 表示不存在。"""
        ...

    async def delete_media(
        self, media_id: str
    ) -> tuple[bool, bool, bool]:
        """删除媒体记录及其文件。

        Returns:
            (deleted_record, deleted_local_file, deleted_object_file)
        """
        ...

    async def list_for_cleanup(
        self,
        older_than_days: Optional[int],
        only_unreferenced: bool,
        limit: int,
    ) -> list[StoredMedia]:
        """列出符合清理条件的媒体。"""
        ...

    async def delete_bulk(
        self, media_ids: list[str]
    ) -> dict[str, tuple[bool, bool, bool]]:
        """批量删除，返回 {media_id: (deleted_record, deleted_local, deleted_object)}。"""
        ...


# ---------------------------------------------------------------------------
# 视频分析 Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class VideoAnalysisProvider(Protocol):
    """视频分析异步任务 provider 接口。

    真实实现示例：GeminiVideoAnalysisProvider
      - start_analysis: 调 Gemini Files API 上传，再调 generateContent 启动分析
      - get_analysis_result: 轮询 Gemini operation 状态，或查本地 DB
      - delete_analysis: 删除 Gemini Files 上传记录 + 本地 job 记录
    """

    async def start_analysis(
        self,
        job_id: str,
        media_id: str,
        input_url: Optional[str],
        analysis_profile: str,
        lang: str,
        output_schema_version: str,
    ) -> VideoAnalysisJob:
        """提交分析任务，返回初始状态（通常为 queued）。

        Raises:
            app.infra.exceptions.NotFoundError: media_id 对应视频不存在
            app.infra.exceptions.ProviderError: Gemini / 上游分析服务不可用
        """
        ...

    async def get_analysis_result(self, job_id: str) -> Optional[VideoAnalysisJob]:
        """查询任务当前状态与结果。返回 None 表示 job_id 不存在。"""
        ...

    async def delete_analysis(self, job_id: str) -> bool:
        """删除任务记录及相关缓存。返回 True 表示记录存在并已删除。"""
        ...


# ---------------------------------------------------------------------------
# 转写 Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class TranscribeProvider(Protocol):
    """转写异步任务 provider 接口。

    真实实现示例：OpenAITranscribeProvider
      - start_transcribe: 调 OpenAI Whisper API 提交音频，返回 job_id
      - get_transcribe_result: 轮询转写状态 / 查本地 DB
      - delete_transcribe: 删除转写记录及 highlights 缓存
    """

    async def start_transcribe(
        self,
        job_id: str,
        media_id: str,
        provider_name: str,
        lang: str,
        mode: str,
    ) -> TranscribeJob:
        """提交转写任务，返回初始状态（通常为 queued）。

        Raises:
            app.infra.exceptions.NotFoundError: media_id 对应媒体不存在
            app.infra.exceptions.ProviderError: 转写服务不可用
        """
        ...

    async def get_transcribe_result(self, job_id: str) -> Optional[TranscribeJob]:
        """查询任务当前状态与结果。返回 None 表示 job_id 不存在。"""
        ...

    async def delete_transcribe(self, job_id: str) -> bool:
        """删除任务记录及相关缓存。返回 True 表示记录存在并已删除。"""
        ...


# ---------------------------------------------------------------------------
# 图片生成 Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class ImageGenerateProvider(Protocol):
    """图片生成异步任务 provider 接口。

    支持文生图（t2i）和图生图/风格迁移（i2i）。

    新增 provider 时：
      1. 在 app/providers/ 下创建 <name>_image_provider.py
      2. 实现本 Protocol 的三个方法
      3. 在 app/routes/image_generate.py 的 IMAGE_PROVIDER 分支中注册

    字段约定：
      - style_reference_path: 风格参考图（本地路径或公网 URL），传入时使用 i2i 模式。
      - model: 运行时模型覆盖。传 None 时使用 provider 默认模型。
    """

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        style_reference_path: Optional[str],
        model: Optional[str],
    ) -> ImageGenerateJob:
        """提交图片生成任务，返回初始状态（通常为 queued）。

        Raises:
            app.infra.exceptions.ProviderError: 上游生成服务不可用
        """
        ...

    async def get_generate_result(self, job_id: str) -> Optional[ImageGenerateJob]:
        """查询任务当前状态与结果。返回 None 表示 job_id 不存在。"""
        ...

    async def delete_generate(self, job_id: str) -> bool:
        """删除任务记录（不删除已下载文件）。返回 True 表示记录存在并已删除。"""
        ...

    @staticmethod
    def available_models() -> list[dict]:
        ...
