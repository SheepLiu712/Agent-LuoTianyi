#!/usr/bin/env python
# coding: utf-8

import argparse
from importlib import import_module
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
# `run_song_workflow.py` 位于
#   server/src/world/get_new_songs/song_learner/run_song_workflow.py
# 需要把 SERVER_ROOT 指向仓库内的 `server` 目录（上溯 3 级），
# 之前使用 parents[4] 多退了一层，导致 ROOT 指向了上一级目录。
SERVER_ROOT = PROJECT_ROOT.parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OUTPUTS_DIR = SERVER_ROOT / "res" / "music" / "songs"
RESOURCE_ROOT = SERVER_ROOT / "res" / "song_learner"

clean_music_workflow = import_module("pipeline.clean_music_workflow")
download_qq_song = import_module("pipeline.download_qq_song")
make_clear_lrc = import_module("pipeline.make_clear_lrc")
make_llm_lrc = import_module("pipeline.make_llm_lrc")
make_song_json = import_module("pipeline.make_song_json")
msaf_segment_boundaries = import_module("pipeline.msaf_segment_boundaries")
workflow_status = import_module("pipeline.workflow_status")

clean_audio_file = clean_music_workflow.clean_audio_file
download_song_and_lyric = download_qq_song.download_song_and_lyric
generate_clear_lrc = make_clear_lrc.generate_clear_lrc
generate_llm_lrc = make_llm_lrc.generate_llm_lrc
generate_song_json = make_song_json.generate_song_json
generate_boundary_inst = msaf_segment_boundaries.generate_boundary_inst
WorkflowStatus = workflow_status.WorkflowStatus


def safe_name(name: str) -> str:
    bad_chars = '<>:"/\\|?*\n\r\t'
    cleaned = "".join("_" if c in bad_chars else c for c in name).strip(" .")
    return cleaned

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键执行歌曲处理工作流（仅需歌曲名）。")
    parser.add_argument("song_name", help="歌曲名，例如：万古生香")
    return parser.parse_args()


def ensure_file(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def find_first(folder: Path, pattern: str) -> Path:
    matches = sorted(folder.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"在目录 {folder} 中未找到: {pattern}")
    return matches[0]


def normalize_song_filename_set(names: set[str], song_name: str) -> set[str]:
    normalized = set()
    for name in names:
        normalized.add(name.replace(song_name, "{song}"))
    return normalized


def sync_output_file_set(target_song_dir: Path, reference_song_dir: Path) -> None:
    target_song_name = target_song_dir.name
    reference_song_name = reference_song_dir.name

    target_names = {p.name for p in target_song_dir.iterdir() if p.is_file()}
    ref_names = {p.name for p in reference_song_dir.iterdir() if p.is_file()}

    # 兼容历史目录：当前流程不再生成 boundary_origin.txt，如参考目录存在则补齐占位文件。
    if "boundary_origin.txt" in ref_names and "boundary_origin.txt" not in target_names:
        inst = target_song_dir / "boundary_inst.txt"
        ensure_file(inst, "boundary_inst")
        shutil.copy2(inst, target_song_dir / "boundary_origin.txt")
        target_names.add("boundary_origin.txt")
        print("[INFO] 已补齐兼容文件: boundary_origin.txt")

    target_names = {p.name for p in target_song_dir.iterdir() if p.is_file()}
    target_norm = normalize_song_filename_set(target_names, target_song_name)
    ref_norm = normalize_song_filename_set(ref_names, reference_song_name)

    if target_norm != ref_norm:
        missing = sorted(ref_norm - target_norm)
        extra = sorted(target_norm - ref_norm)
        raise RuntimeError(
            "输出文件集合与参考目录不一致。"
            f" 缺少: {missing if missing else '无'};"
            f" 多出: {extra if extra else '无'}"
        )


def main() -> None:
    args = parse_args()

    project_root: Path = SERVER_ROOT
    outputs_dir: Path = OUTPUTS_DIR

    song_name = args.song_name.strip()
    if not song_name:
        raise ValueError("song_name 不能为空")

    target_song_dir: Path = outputs_dir / song_name
    target_song_dir.mkdir(parents=True, exist_ok=True)

    # 初始化工作流状态管理
    status = WorkflowStatus(target_song_dir)
    status.print_status()

    # Step 1: 下载 QQ 音乐音频与歌词。
    if status.is_completed("download_song"):
        print("[SKIP] 步骤 download_song 已完成，跳过")
        safe_song_name = song_name
        downloaded_mp3 = find_first(target_song_dir, "*.mp3")
        downloaded_lrc = find_first(target_song_dir, "*.lrc")
    else:
        print("[PROCESS] 正在执行步骤: download_song - 下载歌曲和歌词")
        safe_song_name, downloaded_mp3, downloaded_lrc = download_song_and_lyric(
            song_name=song_name,
            singer_name="洛天依",
            output_dir=outputs_dir,
            credential_file=RESOURCE_ROOT / ".qq_music_credential.json",
        )

    if song_name != safe_song_name:
        # 重命名文件夹以匹配安全的文件名（如果下载的文件名与输入的歌曲名不同）。
        print(f"[INFO] 输入歌曲名 '{song_name}' 与下载文件名 '{safe_song_name}' 不同，正在调整目录结构以匹配安全文件名。")
        new_target_song_dir = outputs_dir / safe_song_name
        new_target_song_dir.mkdir(parents=True, exist_ok=True)
        downloaded_mp3 = downloaded_mp3.rename(new_target_song_dir / downloaded_mp3.name)
        downloaded_lrc = downloaded_lrc.rename(new_target_song_dir / downloaded_lrc.name)
        # 删除tarrget_song_dir下的其他文件（如果有的话），保持目录干净。
        for item in target_song_dir.iterdir():
            if item.is_file():
                item.unlink()
        # 删除target_song_dir目录（如果是空的），保持目录结构干净。
        try:           
            target_song_dir.rmdir()        
        except OSError:
            pass
        target_song_dir = new_target_song_dir
        status = WorkflowStatus(target_song_dir)

    status.mark_completed("download_song")

    # 统一整理到 outputs/<歌名>/ 并固定命名。
    target_cleaned = target_song_dir / f"{safe_song_name}.cleaned.mp3"
    target_inst = target_song_dir / f"{safe_song_name}.inst.mp3"


    # Step 2: 清洗（人声分离+降噪），生成 cleaned / inst。
    if status.is_completed("clean_audio"):
        print("[SKIP] 步骤 clean_audio 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: clean_audio - 清洗音频（人声分离+降噪）")
        cleaned_tmp, inst_tmp = clean_audio_file(
            project_root=project_root,
            input_file=downloaded_mp3,
            output_dir=target_song_dir,
            final_stem_name=safe_song_name,
        )
        ensure_file(cleaned_tmp, "清洗后音频")
        ensure_file(inst_tmp, "伴奏音频")

        if cleaned_tmp.resolve() != target_cleaned.resolve():
            shutil.move(str(cleaned_tmp), str(target_cleaned))
        if inst_tmp.resolve() != target_inst.resolve():
            shutil.move(str(inst_tmp), str(target_inst))
        status.mark_completed("clean_audio")

    # Step 3: 对伴奏做 MSAF，生成 boundary。
    if status.is_completed("generate_boundary"):
        print("[SKIP] 步骤 generate_boundary 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: generate_boundary - 生成边界信息（MSAF）")
        generate_boundary_inst(target_song_dir)
        status.mark_completed("generate_boundary")

    # Step 4: 基于 boundary 生成 clear.lrc。
    if status.is_completed("generate_clear_lrc"):
        print("[SKIP] 步骤 generate_clear_lrc 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: generate_clear_lrc - 生成清晰歌词（clear.lrc）")
        generate_clear_lrc(target_song_dir)
        status.mark_completed("generate_clear_lrc")

    # Step 5: clear.lrc -> llm.lrc。
    if status.is_completed("generate_llm_lrc"):
        print("[SKIP] 步骤 generate_llm_lrc 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: generate_llm_lrc - 生成LLM歌词（llm.lrc）")
        generate_llm_lrc(target_song_dir, prompt_json=RESOURCE_ROOT / "re_segment_prompt.json")
        status.mark_completed("generate_llm_lrc")

    # Step 6: llm.lrc + 原始 lrc -> 最终 json。
    if status.is_completed("generate_song_json"):
        print("[SKIP] 步骤 generate_song_json 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: generate_song_json - 生成最终JSON文件")
        generate_song_json(target_song_dir)
        status.mark_completed("generate_song_json")

    reference_song_dir = outputs_dir / "异样的风暴中心"
    if not reference_song_dir.exists() or not reference_song_dir.is_dir():
        raise NotADirectoryError(f"参考目录不存在: {reference_song_dir}")

    # Step 7: 同步输出文件集合。
    if status.is_completed("sync_output_files"):
        print("[SKIP] 步骤 sync_output_files 已完成，跳过")
    else:
        print("[PROCESS] 正在执行步骤: sync_output_files - 同步输出文件集合")
        sync_output_file_set(target_song_dir=target_song_dir, reference_song_dir=reference_song_dir)
        status.mark_completed("sync_output_files")

    status.print_status()
    print("[SUCCESS] 全流程已完成")
    print(f"[RESULT] 输出目录: {target_song_dir}")


if __name__ == "__main__":
    main()
