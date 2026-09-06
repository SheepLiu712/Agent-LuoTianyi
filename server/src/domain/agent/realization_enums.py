"""计划、输出和执行结算使用的稳定枚举。"""
from enum import Enum


class ActionKind(str, Enum):
    """行动的固定判别值，包括 stage 消费的处理开始通知。"""
    START_THINKING = "start_thinking"
    SAY = "say"
    SING = "sing"
    WRITE_DIARY = "write_diary"
    PUBLISH_DYNAMIC = "publish_dynamic"
    REPLY_DYNAMIC = "reply_dynamic"
    REQUEST_SONG_LEARNING = "request_song_learning"


class OutputDelivery(str, Enum):
    """输出呈现方式：正常对话或不进入聊天记录的瞬时反应。"""
    CONVERSATION = "conversation"
    EPHEMERAL_REACTION = "ephemeral_reaction"


class Visibility(str, Enum):
    """动态可见范围：全局或指定用户私密可见。"""
    GLOBAL = "global"
    PRIVATE = "private"


class PlanAcceptanceStatus(str, Enum):
    """计划成功接收状态；明确拒绝通过 SinkRejectedError 表达。"""
    ACCEPTED = "accepted"
    ALREADY_ACCEPTED = "already_accepted"


class OutputAcceptanceStatus(str, Enum):
    """输出接收状态，只表示接收，不表示客户端播放完成。"""
    ACCEPTED = "accepted"
    ALREADY_ACCEPTED = "already_accepted"


class AudioFraming(str, Enum):
    """音频块是完整编码文件还是需依序拼接的文件片段。"""
    COMPLETE_FILE = "complete_file"
    FILE_FRAGMENT = "file_fragment"


class MessageEndStatus(str, Enum):
    """一条消息生成结束的状态，纯文字消息同样适用。"""
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AudioErrorCode(str, Enum):
    """消息终止时的音频失败原因。"""
    EMPTY_AUDIO = "EMPTY_AUDIO"
    GENERATION_FAILED = "GENERATION_FAILED"


class ExecutionStatus(str, Enum):
    """整个业务计划的执行终态。"""
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionExecutionStatus(str, Enum):
    """单项行动的结果，包括已完成重试和尚未开始。"""
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NOT_STARTED = "not_started"


class EffectKind(str, Enum):
    """持久效果引用的种类，日记使用动态帖子的效果类别。"""
    DYNAMIC_POST = "dynamic_post"
    DYNAMIC_COMMENT = "dynamic_comment"
    SONG_LEARNING_JOB = "song_learning_job"


class ExecutionErrorCode(str, Enum):
    """单项和整体执行的稳定失败原因，取消使用 CANCELLED。"""
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    UNSUPPORTED_OUTPUT = "UNSUPPORTED_OUTPUT"
    STALE_INTERACTION = "STALE_INTERACTION"
    SINK_CLOSED = "SINK_CLOSED"
    BACKPRESSURE_TIMEOUT = "BACKPRESSURE_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    AUDIO_EMPTY = "AUDIO_EMPTY"
    AUDIO_GENERATION_FAILED = "AUDIO_GENERATION_FAILED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
