"""
Auto Song Learner
-----------------
Bridges "user wants a song we can't sing" -> "we can sing it now".

Songlearner pipeline only:
    Download from QQ Music -> vocal separation + denoising -> MSAF segmentation
    -> LLM fine segmentation -> aligned JSON -> songs/
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.domain.music_type import WishEntry
from src.infrastructure.singing.wishlist import WishlistManager
from src.utils.logger import get_logger
from src.utils.helpers import get_unified_song_name


_SONGLEARNER_PATH_ADDED = False


def _add_songlearner_to_path() -> None:
    """将 server 和 song_learner/src 添加到 Python path（幂等）。"""
    global _SONGLEARNER_PATH_ADDED
    if _SONGLEARNER_PATH_ADDED:
        return
    server_root = Path(__file__).resolve().parents[3]
    songlearner_src = Path(__file__).resolve().parent / "song_learner" / "src"
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))
    if str(songlearner_src) not in sys.path:
        sys.path.insert(0, str(songlearner_src))
    _SONGLEARNER_PATH_ADDED = True


@dataclass
class LearnResult:
    """Result from one learning pass."""
    learned: List[str] = field(default_factory=list)
    already_learned: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)
    awaiting: List[str] = field(default_factory=list)


class AutoSongLearner:
    """Orchestrates the learning process.

    Primary path: Songlearner pipeline (download -> clean -> segment -> JSON).
    """

    MAX_ATTEMPTS = 3
    SONGELEARNER_TIMEOUT = 1200  # 20 minutes max for the full pipeline

    def __init__(
        self,
        config: Dict[str, Any],
        character_name: str,
        wishlist: WishlistManager,
        *,
        resource_path: str | Path | None = None,
    ):
        self.logger = get_logger("AutoSongLearner")
        config = config or {}
        self.character_name = character_name
        cwd = Path.cwd()
        configured_resource_path = resource_path or config.get("resource_path")
        if not configured_resource_path:
            raise ValueError("AutoSongLearner requires resource_path from SingingManager")
        self.resource_path = self._resolve_path(cwd, configured_resource_path)
        self.songs_dir = self.resource_path / "songs"
        self.metadata_path = self.resource_path / "metadata.json"
        self.wishlist = wishlist
        self._ensure_directories()

        # Songlearner integration
        self.songlearner_dir = cwd / Path(config.get("songlearner_dir", "src/world/learn_sing_songs/song_learner"))
        self.songlearner_resource_dir = cwd / Path(config.get("songlearner_resource_dir", "res/song_learner"))
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
        credential_path = config.get("qq_credential_file", "config/qq_music_credential.json")
        self._credential_file = self._resolve_path(cwd, credential_path)
        self.qq_credential_refresh_before_seconds = max(
            0,
            int(config.get("qq_credential_refresh_before_seconds", 86400)),
        )
        self._migrate_legacy_qq_credential()
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

    @staticmethod
    def _resolve_path(cwd: Path, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return cwd / path

    def _ensure_directories(self) -> None:
        self.songs_dir.mkdir(parents=True, exist_ok=True)

    # -- QQ 凭证管理 ---------------------------------------------------------

    def _validate_qq_credential(self) -> bool:
        """启动时验证本地凭证格式；服务端检查由定时任务立即执行。"""
        try:
            # song_learner/src 需要在 Python path 中
            _add_songlearner_to_path()
            download_qq_song = importlib.import_module("pipeline.download_qq_song")
            saved = download_qq_song.load_saved_credential(self._credential_file)
            if saved and download_qq_song.validate_credential(saved):
                self.logger.info(f"QQ 音乐凭证格式有效: {self._credential_file}")
                return True
        except Exception as e:
            self.logger.warning(f"QQ 音乐凭证检测异常: {e}")
        return False

    def _ensure_qq_credential_fresh(self) -> bool:
        try:
            _add_songlearner_to_path()
            download_qq_song = importlib.import_module("pipeline.download_qq_song")
            download_qq_song.ensure_fresh_credential(
                self._credential_file,
                refresh_before_seconds=self.qq_credential_refresh_before_seconds,
                check_remote=True,
            )
            self.logger.info(f"QQ 音乐凭证有效且已完成续期检查: {self._credential_file}")
            return True
        except Exception as e:
            self.logger.warning(f"QQ 音乐凭证自动续期失败: {e}")
            return False

    def _migrate_legacy_qq_credential(self) -> None:
        legacy_file = self.songlearner_resource_dir / ".qq_music_credential.json"
        if self._credential_file.exists() or not legacy_file.exists():
            return
        try:
            self._credential_file.parent.mkdir(parents=True, exist_ok=True)
            self._credential_file.write_text(legacy_file.read_text(encoding="utf-8"), encoding="utf-8")
            self.logger.info(f"已迁移 QQ 音乐凭证: {legacy_file} -> {self._credential_file}")
        except Exception as e:
            self.logger.warning(f"迁移 QQ 音乐凭证失败: {e}")

    def _generate_login_qr(self) -> None:
        """生成 QQ 登录二维码并保存到文件（不等待扫码）。"""
        try:
            _add_songlearner_to_path()
            download_qq_song = importlib.import_module("pipeline.download_qq_song")
            qr_path = self._credential_file.parent / "qq_login_qr.png"
            success = download_qq_song._run_async_from_sync(
                download_qq_song.generate_qr_only(qr_path)
            )
            if success:
                self.logger.info(f"QQ 登录二维码已生成: {qr_path}")
            else:
                self.logger.warning("生成 QQ 登录二维码失败（qqmusic-api 可能未安装）")
        except Exception as e:
            self.logger.warning(f"生成 QQ 登录二维码异常: {e}")

    def check_qq_credential(self) -> bool:
        """
        公开方法：服务端检查 QQ 音乐凭证，并在到期前自动续期。
        供定时刷新和每次学歌任务的前置检查调用。无效时重新生成二维码。
        """
        if not self.songlearner_available:
            return False
        valid = self._ensure_qq_credential_fresh()
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
        """Try to learn all pending wished songs. Called by the world clock task."""
        result = LearnResult()
        pending = self.wishlist.get_pending()
        if not pending:
            self.logger.info("No pending songs to learn")
            return result

        self.logger.info(f"Attempting to learn {len(pending)} pending song(s)")
        known_song_names = self._get_existing_song_names()

        for entry in pending:
            safe_name = entry.safe_name
            self.logger.info(f"Trying to learn: {safe_name}")
            try:
                requested_unified = get_unified_song_name(safe_name)
                if requested_unified in known_song_names:
                    self.wishlist.mark_learned(safe_name)
                    result.already_learned.append(safe_name)
                    self.logger.info(f"  ↷ Already learned, skipped: {safe_name}")
                    continue

                learned_name = self._try_learn_one(safe_name)
                if learned_name:
                    learned_unified = get_unified_song_name(learned_name)
                    if learned_unified in known_song_names:
                        if learned_name not in result.already_learned:
                            result.already_learned.append(learned_name)
                        self.logger.info(
                            f"  ↷ Redirected to already learned song, no notification: "
                            f"{safe_name} -> {learned_name}"
                        )
                        continue

                    result.learned.append(learned_name)
                    if learned_unified:
                        known_song_names.add(learned_unified)
                    if get_unified_song_name(learned_name) != get_unified_song_name(safe_name):
                        self.logger.info(f"  ✓ Learned via redirect: {safe_name} -> {learned_name}")
                    else:
                        self.logger.info(f"  ✓ Learned: {safe_name}")
                else:
                    unified_name = get_unified_song_name(safe_name)
                    entry_after = self.wishlist.wished_songs.get(unified_name)
                    if entry_after and entry_after.status == "redirected":
                        redirected_name = entry_after.redirected_to or safe_name
                        if entry_after.redirected_status == "abandoned":
                            result.abandoned.append(redirected_name)
                            self.logger.info(f"  ✗ Redirected target abandoned: {safe_name} -> {redirected_name}")
                        else:
                            result.awaiting.append(redirected_name)
                            self.logger.info(f"  ... Redirected target awaiting: {safe_name} -> {redirected_name}")
                    elif entry_after and entry_after.status == "abandoned":
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

    def _get_existing_song_names(self) -> set[str]:
        """Collect valid songs already present in the character's singing library."""
        existing: set[str] = set()
        if not self.songs_dir.exists():
            return existing

        for song_dir in self.songs_dir.iterdir():
            if not song_dir.is_dir():
                continue
            song_name = song_dir.name
            has_audio = (
                (song_dir / f"{song_name}.cleaned.mp3").is_file()
                or (song_dir / f"{song_name}.mp3").is_file()
            )
            lrc_path = song_dir / f"{song_name}.lrc"
            json_path = song_dir / f"{song_name}.json"
            if not has_audio or not lrc_path.is_file() or not json_path.is_file():
                continue

            unified_dir_name = get_unified_song_name(song_name)
            if unified_dir_name:
                existing.add(unified_dir_name)
            try:
                title = str(json.loads(json_path.read_text("utf-8")).get("title") or "")
            except Exception:
                title = ""
            unified_title = get_unified_song_name(title)
            if unified_title:
                existing.add(unified_title)
        return existing

    # -- routing -------------------------------------------------------------

    def _try_learn_one(self, safe_name: str) -> Optional[str]:
        """Route to Songlearner pipeline."""
        if not safe_name or ".." in safe_name or "/" in safe_name or "\\" in safe_name:
            self.logger.error(f"Invalid safe_name rejected: {safe_name!r}")
            return None
        if not self.songlearner_available:
            self.logger.error(f"Songlearner 不可用，无法学习: {safe_name}")
            return None
        return self._learn_via_songlearner(safe_name)

    # -- Songlearner pipeline ------------------------------------------------

    def _learn_via_songlearner(self, safe_name: str) -> Optional[str]:
        """Full Songlearner pipeline: download -> clean -> MSAF -> LLM -> JSON."""
        runner = self.songlearner_dir / "run_song_workflow.py"
        if not runner.exists():
            self.logger.error(f"Songlearner 启动脚本不存在: {runner}")
            self._handle_failure(safe_name, f"SL001 startup: Songlearner 启动脚本不存在: {runner}")
            return None

        self.logger.info(f"[Songlearner] 开始学习: {safe_name}")
        env = self._build_songlearner_env()

        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    safe_name,
                    "--output_dir",
                    str(self.songs_dir),
                    "--resource_root",
                    str(self.songlearner_resource_dir),
                    "--credential_file",
                    str(self._credential_file),
                    "--no_auto_login",
                    "--singer_name",
                    self.character_name,
                ],
                cwd=str(self.songlearner_dir),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.SONGELEARNER_TIMEOUT,
                env=env,
            )
        except subprocess.TimeoutExpired:
            self._handle_failure(safe_name, "SL091 timeout: Songlearner 流水线执行超时（>20分钟）")
            return None

        if proc.returncode != 0:
            failure_reason = self._format_songlearner_failure(proc)
            redirected_name = self._parse_songlearner_redirect(proc.stdout)
            self.logger.error(
                f"[Songlearner] 流水线返回非零退出码 {proc.returncode}\n"
                f"stderr: {proc.stderr[-500:] if proc.stderr else ''}"
            )
            if redirected_name and get_unified_song_name(redirected_name) != get_unified_song_name(safe_name):
                self.wishlist.mark_redirected(
                    safe_name,
                    redirected_name,
                    redirected_status="awaiting_audio",
                    reason=failure_reason,
                )
                redirected_status = self._handle_failure(redirected_name, failure_reason, create_if_missing=True)
                self.wishlist.update_redirect_status(safe_name, redirected_status, failure_reason)
            else:
                self._handle_failure(safe_name, failure_reason)
            return None

        # Locate the final output directory under the music library.
        learned_name = self._parse_songlearner_result(proc.stdout) or safe_name
        sl_output = self.songs_dir / learned_name
        print(f"Looking for Songlearner output at: {sl_output}")
        if not sl_output.exists():
            # The workflow may have normalized the folder name.
            outputs_root = self.songs_dir
            if outputs_root.exists():
                candidates = sorted(outputs_root.iterdir(), key=os.path.getmtime, reverse=True)
                for c in candidates:
                    if c.is_dir() and (c / f"{c.name}.json").exists():
                        sl_output = c
                        learned_name = c.name
                        self.logger.info(f"[Songlearner] 输出目录重定向至: {sl_output.name}")
                        break
                else:
                    self._handle_failure(safe_name, "SL092 finalize: Songlearner 未生成任何有效输出目录")
                    return None
            else:
                self._handle_failure(safe_name, "SL092 finalize: 歌曲输出目录不存在")
                return None

        return self._finalize_song(safe_name, learned_name, sl_output)

    def _format_songlearner_failure(self, proc: subprocess.CompletedProcess) -> str:
        stderr = proc.stderr or ""
        parsed = self._parse_songlearner_error(stderr)
        if parsed:
            return (
                f"{parsed['code']} {parsed['step']}: {parsed['message']} "
                f"(exit_code={parsed['exit_code']})"
            )

        stderr_tail = self._last_nonempty_line(stderr) or "无 stderr"
        return f"SL099 unexpected: Songlearner 流水线执行失败，退出码 {proc.returncode}: {stderr_tail}"

    def _parse_songlearner_error(self, stderr: str) -> Optional[Dict[str, str]]:
        pattern = re.compile(
            r"\[SONGLEARNER_ERROR\]\s+"
            r"code=(?P<code>\S+)\s+"
            r"exit_code=(?P<exit_code>\d+)\s+"
            r"step=(?P<step>\S+)\s+"
            r"message=(?P<message>.*)"
        )
        for line in reversed((stderr or "").splitlines()):
            match = pattern.search(line.strip())
            if match:
                return match.groupdict()
        return None

    def _parse_songlearner_result(self, stdout: str) -> str:
        for line in reversed((stdout or "").splitlines()):
            match = re.search(r"\[RESULT\]\s+song_name:\s*(?P<song_name>.+)\s*$", line.strip())
            if match:
                return match.group("song_name").strip()
        return ""

    def _parse_songlearner_redirect(self, stdout: str) -> str:
        for line in reversed((stdout or "").splitlines()):
            match = re.search(
                r"\[REDIRECT\]\s+requested_song_name=(?P<requested>.*?)\s+actual_song_name=(?P<actual>.+)\s*$",
                line.strip(),
            )
            if match:
                return match.group("actual").strip()
        return self._parse_songlearner_result(stdout)

    def _last_nonempty_line(self, text: str, limit: int = 300) -> str:
        for line in reversed((text or "").splitlines()):
            stripped = line.strip()
            if stripped:
                return stripped[-limit:]
        return ""

    def _build_songlearner_env(self) -> dict[str, str]:
        server_root = Path(__file__).resolve().parents[3]
        songlearner_src = self.songlearner_dir / "src"
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath_parts = [str(songlearner_src), str(server_root)]
        if existing_pythonpath:
            pythonpath_parts.append(existing_pythonpath)
        return {
            **os.environ,
            "QWEN_API_KEY": os.environ.get("QWEN_API_KEY", ""),
            "SILICONFLOW_API_KEY": os.environ.get("SILICONFLOW_API_KEY", ""),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
            "TEST_SONGS_DIR": str(self.songs_dir),
            "SONGLEARNER_RESOURCE_DIR": str(self.songlearner_resource_dir),
            "SONGLEARNER_QQ_CREDENTIAL_FILE": str(self._credential_file),
        }

    def _finalize_song(self, requested_name: str, learned_name: str, src_dir: Path) -> Optional[str]:
        """Validate and finalize the workflow output in place."""
        target_dir = src_dir
        if not target_dir.exists() or not target_dir.is_dir():
            self._handle_failure(requested_name, f"SL092 finalize: 歌曲输出目录不存在: {target_dir}")
            return None

        learned_name = learned_name or target_dir.name
        cleaned_target = target_dir / f"{learned_name}.cleaned.mp3"
        raw_mp3 = target_dir / f"{learned_name}.mp3"
        json_path = target_dir / f"{learned_name}.json"

        if not cleaned_target.exists() and raw_mp3.exists():
            self.logger.warning(f"  - 未找到清洗后音频，继续使用原始 MP3: {raw_mp3.name}")
            cleaned_target = raw_mp3

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text("utf-8"))
                if "description" not in data:
                    data["description"] = f"{self.character_name}演唱的歌曲《{learned_name}》"
                # Ensure title field is set
                if not data.get("title"):
                    data["title"] = learned_name
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
                requested_name,
                f"SL093 finalize: 关键文件缺失: audio={has_audio}, json={has_json}",
            )
            return None

        if get_unified_song_name(requested_name) != get_unified_song_name(learned_name):
            self.wishlist.mark_redirected(
                requested_name,
                learned_name,
                redirected_status="learned",
                reason="QQ 音乐搜索结果重定向",
            )
        self.wishlist.mark_learned(learned_name)
        self.logger.info(f"[Songlearner] ✓ 学习完成: {learned_name}")
        return learned_name

    # (Removed LRC parsing and auto-segmentation helpers; staging fallback removed.)

    # -- failure handling ----------------------------------------------------

    def _handle_failure(self, safe_name: str, reason: str, *, create_if_missing: bool = False) -> str:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wishlist.wished_songs.get(unified_name)
        if entry is None and create_if_missing:
            entry = WishEntry(
                safe_name=safe_name,
                unified_name=unified_name,
                first_requested=time.strftime("%Y-%m-%d"),
            )
            self.wishlist.wished_songs[unified_name] = entry
        if entry is None:
            return ""
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
        return entry.status

    # -- notification --------------------------------------------------------

    def _notify_new_songs(self, learned: List[str]) -> None:
        """Write learned songs so the Stage reminder path can announce them."""
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
