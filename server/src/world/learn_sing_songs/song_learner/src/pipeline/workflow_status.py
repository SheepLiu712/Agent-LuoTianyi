#!/usr/bin/env python
# coding: utf-8

"""
工作流状态管理模块

管理输出文件夹中的 workflow_status.json 文件，记录每个步骤的完成状态。
"""

import json
from pathlib import Path


# 工作流步骤定义
WORKFLOW_STEPS = {
    "download_song": "下载歌曲和歌词",
    "clean_audio": "清洗音频（人声分离+降噪）",
    "generate_boundary": "生成边界信息（MSAF）",
    "generate_clear_lrc": "生成清晰歌词（clear.lrc）",
    "generate_llm_lrc": "生成LLM歌词（llm.lrc）",
    "generate_song_json": "生成最终JSON文件",
    "sync_output_files": "同步输出文件集合",
}


class WorkflowStatus:
    """工作流状态管理类"""
    
    def __init__(self, song_dir: Path):
        """
        初始化状态管理器
        
        Args:
            song_dir: 歌曲输出目录（如 outputs/万古生香）
        """
        self.song_dir = Path(song_dir)
        self.status_file = self.song_dir / "workflow_status.json"
        self._load_or_create()
    
    def _load_or_create(self) -> None:
        """从文件加载状态，或创建新的状态文件"""
        if self.status_file.exists():
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    self.status = json.load(f)
                # 确保所有步骤都存在
                for step in WORKFLOW_STEPS:
                    if step not in self.status:
                        self.status[step] = False
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARNING] 无法读取状态文件 {self.status_file}，将创建新文件: {e}")
                self._create_default_status()
        else:
            self._create_default_status()
    
    def _create_default_status(self) -> None:
        """创建默认状态"""
        self.status = {step: False for step in WORKFLOW_STEPS}
        self._save()
    
    def _save(self) -> None:
        """保存状态到文件"""
        self.song_dir.mkdir(parents=True, exist_ok=True)
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(self.status, f, indent=2, ensure_ascii=False)
    
    def is_completed(self, step: str) -> bool:
        """
        检查某个步骤是否已完成
        
        Args:
            step: 步骤名称
            
        Returns:
            True 表示已完成，False 表示未完成
        """
        if step not in WORKFLOW_STEPS:
            raise ValueError(f"未知的步骤: {step}")
        return self.status.get(step, False)
    
    def mark_completed(self, step: str) -> None:
        """
        标记某个步骤为已完成
        
        Args:
            step: 步骤名称
        """
        if step not in WORKFLOW_STEPS:
            raise ValueError(f"未知的步骤: {step}")
        self.status[step] = True
        self._save()
        print(f"[INFO] 已标记步骤为完成: {step} - {WORKFLOW_STEPS[step]}")
    
    def mark_incomplete(self, step: str) -> None:
        """
        标记某个步骤为未完成（用于重新运行）
        
        Args:
            step: 步骤名称
        """
        if step not in WORKFLOW_STEPS:
            raise ValueError(f"未知的步骤: {step}")
        self.status[step] = False
        self._save()
        print(f"[INFO] 已标记步骤为未完成: {step} - {WORKFLOW_STEPS[step]}")
    
    def get_all_status(self) -> dict:
        """获取所有步骤的状态"""
        return self.status.copy()
    
    def reset_all(self) -> None:
        """重置所有步骤为未完成"""
        self._create_default_status()
        print("[INFO] 已重置所有步骤状态")
    
    def print_status(self) -> None:
        """打印当前状态"""
        print("\n[工作流状态]")
        for step, desc in WORKFLOW_STEPS.items():
            status = "✓ 已完成" if self.status.get(step, False) else "✗ 未完成"
            print(f"  {status}: {step} - {desc}")
        print()
