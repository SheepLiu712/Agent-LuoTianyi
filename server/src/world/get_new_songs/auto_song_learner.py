"""
Auto Song Learner
-----------------
Bridges "user wants a song we can't sing" -> "we can sing it now".

Songlearner pipeline only:
    Download from QQ Music -> vocal separation + denoising -> MSAF segmentation
    -> LLM fine segmentation -> aligned JSON -> songs/
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.domain.music_type import WishEntry
from src.utils.logger import get_logger
from src.utils.helpers import get_unified_song_name


_SONGLEARNER_PATH_ADDED = False


def _add_songlearner_to_path() -> None:
    """将 song_learner/src 添加到 Python path（幂等）。"""
    global _SONGLEARNER_PATH_ADDED
    if _SONGLEARNER_PATH_ADDED:
        return
    songlearner_src = Path(__file__).resolve().parent / "song_learner" / "src"
    if str(songlearner_src) not in sys.path:
        sys.path.insert(0, str(songlearner_src))
    _SONGLEARNER_PATH_ADDED = True


@dataclass
class LearnResult:
    """Result from one learning pass."""
    learned: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)
    awaiting: List[str] = field(default_factory=list)


class WishlistManager:
    """Manages the enhanced metadata.json wishlist with v1->v2 migration."""

    def __init__(self, metadata_path: str, logger: Any):
        self.metadata_path = Path(metadata_path)
        self.logger = logger
        self.wished_songs: Dict[str, WishEntry] = {}
        self.recently_learned: List[str] = []
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self.metadata_path.exists():
            self.logger.info("metadata.json not found, starting fresh wishlist")
            return
        try:
            raw = json.loads(self.metadata_path.read_text("utf-8"))
        except Exception as e:
            self.logger.warning(f"Failed to parse metadata.json: {e}, starting fresh")
            return

        wished_raw = raw.get("wished_songs", {})
        if isinstance(wished_raw, list):
            self.logger.info("Migrating v1 wishlist (flat list) to v2 (dict)")
            for name in wished_raw:
                self.wished_songs[name] = WishEntry(safe_name=name)
            raw["wished_songs"] = {
                name: self._entry_to_dict(e)
                for name, e in self.wished_songs.items()
            }
            raw.setdefault("recently_learned", [])
            self._atomic_write(raw)
        elif isinstance(wished_raw, dict):
            for name, entry_dict in wished_raw.items():
                self.wished_songs[name] = WishEntry(**entry_dict)

        self.recently_learned = raw.get("recently_learned", [])

    def _save(self) -> None:
        data = {
            "wished_songs": {
                name: self._entry_to_dict(e)
                for name, e in self.wished_songs.items()
            },
            "recently_learned": self.recently_learned,
        }
        self._atomic_write(data)

    def _atomic_write(self, data: dict) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.metadata_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.metadata_path)

    @staticmethod
    def _entry_to_dict(e: WishEntry) -> dict:
        d = asdict(e)
        return {k: v for k, v in d.items() if v}

    # -- public API ----------------------------------------------------------

    def add(self, safe_name: str) -> bool:
        """Record or increment a wished song. Returns True if entry was created."""
        safe_name = safe_name.strip().strip("《》")
        unified_name = get_unified_song_name(safe_name)
        if not safe_name:
            return False
        if unified_name in self.wished_songs:
            self.wished_songs[unified_name].request_count += 1
            self._save()
            return False
        self.wished_songs[unified_name] = WishEntry(
            safe_name=safe_name,
            unified_name=unified_name,
            first_requested=time.strftime("%Y-%m-%d"),
        )
        self._save()
        return True

    def get_pending(self) -> List[WishEntry]:
        """Return entries that need a learning attempt."""
        return [
            e for e in self.wished_songs.values()
            if e.status in ("pending", "awaiting_audio")
            and e.attempt_count < 3
        ]

    def mark_learned(self, safe_name: str) -> None:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wished_songs.get(unified_name)
        if entry is None:
            return
        entry.status = "learned"
        entry.learned_date = time.strftime("%Y-%m-%d")
        self.recently_learned.append(unified_name)
        self._save()

    def mark_awaiting_audio(self, safe_name: str, reason: str = "") -> None:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wished_songs.get(unified_name)
        if entry is None:
            return
        entry.status = "awaiting_audio"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def mark_abandoned(self, safe_name: str, reason: str = "") -> None:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wished_songs.get(unified_name)
        if entry is None:
            return
        entry.status = "abandoned"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def get_recently_learned(self) -> List[str]:
        """Return and clear the recently-learned notification list."""
        result = list(self.recently_learned)
        if result:
            self.recently_learned = []
            self._save()
        return result

    def get_all(self) -> Dict[str, WishEntry]:
        return dict(self.wished_songs)

    def sync_existing_songs(self, all_safe_names: set) -> None:
        """Mark any wished songs that now exist in the library as learned."""
        changed = False
        for safe_name in all_safe_names:
            unified_name = get_unified_song_name(safe_name)
            entry = self.wished_songs.get(unified_name)
            if entry and entry.status not in ("learned", "abandoned"):
                entry.status = "learned"
                entry.learned_date = time.strftime("%Y-%m-%d")
                changed = True
        if changed:
            self._save()


class AutoSongLearner:
    """Orchestrates the learning process.

    Primary path: Songlearner pipeline (download -> clean -> segment -> JSON).
    """

    MAX_ATTEMPTS = 3
    SONGELEARNER_TIMEOUT = 1200  # 20 minutes max for the full pipeline

    def __init__(self, config: Dict[str, Any], wishlist: WishlistManager):
        self.logger = get_logger("AutoSongLearner")
        config = config or {}
        self.resource_path = os.getcwd() / Path(config.get("resource_path", "res/music"))
        self.songs_dir = self.resource_path / "songs"
        self.metadata_path = self.resource_path / "metadata.json"
        self.wishlist = wishlist
        self._ensure_directories()

        # Songlearner integration
        self.songlearner_dir = os.getcwd() / Path(config.get("songlearner_dir", "src/plugins/music/song_learner"))
        self.songlearner_resource_dir = os.getcwd() / Path(config.get("songlearner_resource_dir", "res/song_learner"))
        self.songlearner_available = self._check_songlearner_models()
        if self.songlearner_available:
            self.logger.info("Songlearner 模型已就绪，将使用完整学歌流水线（QQ音乐下载->清洗->MSAF->LLM分段）")
        else:
            self.logger.error(
                "Songlearner 模型未就绪（需下载 MSST 预训练权重），"
                "无法执行自动学歌"
            )
            raise RuntimeError("Songlearner 模型未就绪，无法执行自动学歌")

        # QQ 音乐凭证检测（启动时）
        self._credential_file = self.songlearner_resource_dir / ".qq_music_credential.json"
        self.qq_credential_valid = self._validate_qq_credential()
        if not self.qq_credential_valid:
            self.logger.warning(
                "QQ 音乐凭证无效或不存在，正在生成登录二维码..."
            )
            self._generate_login_qr()
            self.logger.warning(
                f"请用 QQ 扫描二维码完成登录: {self.songlearner_resource_dir / 'qq_login_qr.png'}"
            )

    # -- directory setup -----------------------------------------------------

    def _ensure_directories(self) -> None:
        self.songs_dir.mkdir(parents=True, exist_ok=True)

    # -- QQ 凭证管理 ---------------------------------------------------------

    def _validate_qq_credential(self) -> bool:
        """加载并验证本地 QQ 音乐凭证。"""
        try:
            # song_learner/src 需要在 Python path 中
            _add_songlearner_to_path()
            download_qq_song = importlib.import_module("pipeline.download_qq_song")
            saved = download_qq_song.load_saved_credential(self._credential_file)
            if saved and download_qq_song.validate_credential(saved):
                self.logger.info(f"QQ 音乐凭证有效: {self._credential_file}")
                return True
        except Exception as e:
            self.logger.warning(f"QQ 音乐凭证检测异常: {e}")
        return False

    def _generate_login_qr(self) -> None:
        """生成 QQ 登录二维码并保存到文件（不等待扫码）。"""
        try:
            _add_songlearner_to_path()
            download_qq_song = importlib.import_module("pipeline.download_qq_song")
            qr_path = self._credential_file.parent / "qq_login_qr.png"
            success = asyncio.run(download_qq_song.generate_qr_only(qr_path))
            if success:
                self.logger.info(f"QQ 登录二维码已生成: {qr_path}")
            else:
                self.logger.warning("生成 QQ 登录二维码失败（qqmusic-api 可能未安装）")
        except Exception as e:
            self.logger.warning(f"生成 QQ 登录二维码异常: {e}")

    def check_qq_credential(self) -> bool:
        """
        公开方法：重新检查 QQ 音乐凭证有效性。
        供 DailyScheduler 凌晨调用。无效时重新生成二维码。
        """
        if not self.songlearner_available:
            return False
        valid = self._validate_qq_credential()
        self.qq_credential_valid = valid
        if not valid:
            self.logger.warning(
                "QQ 音乐凭证仍然无效，重新生成登录二维码..."
            )
            self._generate_login_qr()
            self.logger.warning(
                f"请用 QQ 扫描二维码完成登录: {self.songlearner_resource_dir / 'qq_login_qr.png'}"
            )
        return valid

    # -- main entry ----------------------------------------------------------

    def try_learn_pending(self) -> LearnResult:
        """Try to learn all pending wished songs. Called by DailyScheduler."""
        result = LearnResult()
        pending = self.wishlist.get_pending()
        if not pending:
            self.logger.info("No pending songs to learn")
            return result

        self.logger.info(f"Attempting to learn {len(pending)} pending song(s)")

        for entry in pending:
            safe_name = entry.safe_name
            self.logger.info(f"Trying to learn: {safe_name}")
            try:
                if self._try_learn_one(safe_name):
                    result.learned.append(safe_name)
                    self.logger.info(f"  ✓ Learned: {safe_name}")
                else:
                    unified_name = get_unified_song_name(safe_name)
                    entry_after = self.wishlist.wished_songs.get(unified_name)
                    if entry_after and entry_after.status == "abandoned":
                        result.abandoned.append(safe_name)
                        self.logger.info(f"  ✗ Abandoned: {safe_name}")
                    else:
                        result.awaiting.append(safe_name)
                        self.logger.info(f"  ... Still awaiting: {safe_name}")
            except Exception as exc:
                self.logger.error(f"  ! Error learning {safe_name}: {exc}")
                result.awaiting.append(safe_name)

        if result.learned:
            self._notify_new_songs(result.learned)

        return result

    # -- routing -------------------------------------------------------------

    def _try_learn_one(self, safe_name: str) -> bool:
        """Route to Songlearner pipeline."""
        if not safe_name or ".." in safe_name or "/" in safe_name or "\\" in safe_name:
            self.logger.error(f"Invalid safe_name rejected: {safe_name!r}")
            return False
        if not self.songlearner_available:
            self.logger.error(f"Songlearner 不可用，无法学习: {safe_name}")
            return False
        return self._learn_via_songlearner(safe_name)

    # -- Songlearner pipeline ------------------------------------------------

    def _learn_via_songlearner(self, safe_name: str) -> bool:
        """Full Songlearner pipeline: download -> clean -> MSAF -> LLM -> JSON."""
        runner = self.songlearner_dir / "run_song_workflow.py"
        if not runner.exists():
            self.logger.error(f"Songlearner 启动脚本不存在: {runner}")
            self._handle_failure(safe_name, f"Songlearner 启动脚本不存在: {runner}")
            return False

        self.logger.info(f"[Songlearner] 开始学习: {safe_name}")

        try:
            proc = subprocess.run(
                [sys.executable, str(runner), safe_name],
                cwd=str(self.songlearner_dir),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.SONGELEARNER_TIMEOUT,
                env={
                    **os.environ,
                    "QWEN_API_KEY": os.environ.get("QWEN_API_KEY", ""),
                    "SILICONFLOW_API_KEY": os.environ.get("SILICONFLOW_API_KEY", ""),
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "TEST_SONGS_DIR": str(self.songs_dir),
                },
            )
        except subprocess.TimeoutExpired:
            self._handle_failure(safe_name, "Songlearner 流水线执行超时（>20分钟）")
            return False

        if proc.returncode != 0:
            self.logger.error(
                f"[Songlearner] 流水线返回非零退出码 {proc.returncode}\n"
                f"stderr: {proc.stderr[-500:] if proc.stderr else ''}"
            )
            self._handle_failure(safe_name, f"Songlearner 流水线执行失败，退出码 {proc.returncode}")
            return False

        # Locate the final output directory under the music library.
        sl_output = self.songs_dir / safe_name
        print(f"Looking for Songlearner output at: {sl_output}")
        if not sl_output.exists():
            # The workflow may have normalized the folder name.
            outputs_root = self.songs_dir
            if outputs_root.exists():
                candidates = sorted(outputs_root.iterdir(), key=os.path.getmtime, reverse=True)
                for c in candidates:
                    if c.is_dir() and (c / f"{c.name}.json").exists():
                        sl_output = c
                        safe_name = c.name
                        self.logger.info(f"[Songlearner] 输出目录重定向至: {sl_output.name}")
                        break
                else:
                    self._handle_failure(safe_name, "Songlearner 未生成任何有效输出目录")
                    return False
            else:
                self._handle_failure(safe_name, "歌曲输出目录不存在")
                return False

        return self._finalize_song(safe_name, sl_output)

    def _finalize_song(self, safe_name: str, src_dir: Path) -> bool:
        """Validate and finalize the workflow output in place."""
        target_dir = src_dir
        if not target_dir.exists() or not target_dir.is_dir():
            self._handle_failure(safe_name, f"歌曲输出目录不存在: {target_dir}")
            return False

        cleaned_target = target_dir / f"{safe_name}.cleaned.mp3"
        raw_mp3 = target_dir / f"{safe_name}.mp3"
        json_path = target_dir / f"{safe_name}.json"

        if not cleaned_target.exists() and raw_mp3.exists():
            self.logger.warning(f"  - 未找到清洗后音频，继续使用原始 MP3: {raw_mp3.name}")
            cleaned_target = raw_mp3

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text("utf-8"))
                if "description" not in data:
                    data["description"] = f"洛天依演唱的歌曲《{safe_name}》"
                # Ensure title field is set
                if not data.get("title"):
                    data["title"] = safe_name
                json_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                self.logger.error(f"JSON 后处理失败: {e}")

        # Validate
        has_audio = cleaned_target.exists()
        has_json = json_path.exists()
        if not has_audio or not has_json:
            self._handle_failure(
                safe_name,
                f"关键文件缺失: audio={has_audio}, json={has_json}",
            )
            return False

        self.wishlist.mark_learned(safe_name)
        self.logger.info(f"[Songlearner] ✓ 学习完成: {safe_name}")
        return True

    # (Removed LRC parsing and auto-segmentation helpers; staging fallback removed.)

    # -- failure handling ----------------------------------------------------

    def _handle_failure(self, safe_name: str, reason: str) -> None:
        entry = self.wishlist.wished_songs.get(safe_name)
        if entry is None:
            return
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        if entry.attempt_count >= self.MAX_ATTEMPTS:
            entry.status = "abandoned"
            self.logger.warning(f"Abandoned learning {safe_name} after {self.MAX_ATTEMPTS} attempts: {reason}")
        else:
            entry.status = "awaiting_audio"
            self.logger.info(f"Learning {safe_name} awaits audio (attempt {entry.attempt_count}/{self.MAX_ATTEMPTS}): {reason}")
        self.wishlist._save()

    # -- notification --------------------------------------------------------

    def _notify_new_songs(self, learned: List[str]) -> None:
        """Write learned songs so ActivityMaker can announce them on next login."""
        notify_dir = Path("data/plugin_scheduler")
        notify_dir.mkdir(parents=True, exist_ok=True)
        notify_path = notify_dir / "newly_learned_songs.json"
        existing: List[str] = []
        if notify_path.exists():
            try:
                existing = json.loads(notify_path.read_text("utf-8"))
            except Exception:
                pass
        notify_path.write_text(
            json.dumps(existing + learned, ensure_ascii=False), encoding="utf-8"
        )
        self.logger.info(f"Notification written: {learned}")

    @property
    def recently_learned(self) -> List[str]:
        return self.wishlist.get_recently_learned()

        # -- model check ---------------------------------------------------------

    def _check_songlearner_models(self) -> bool:
        """Check if Songlearner resources are downloaded under res/song_learner/."""
        required_models = [
            "msst/configs/model_bs_roformer_ep_317_sdr_12.9755.yaml",
            "msst/pretrain/model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "msst/configs/model_mel_band_roformer_denoise.yaml",
            "msst/pretrain/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt",
            "re_segment_prompt.json",
        ]
        for rel_path in required_models:
            if not (self.songlearner_resource_dir / rel_path).exists():
                self.logger.warning(f"Songlearner 模型缺失: {rel_path}")
                return False
        return True
