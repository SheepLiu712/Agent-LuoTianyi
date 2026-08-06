"""
辅助脚本：为动态对话框构造测试数据（含日记条目），
用于验证日记在 PC 客户端动态列表和详情中的显示效果。

用法：
  1. 确保客户端依赖已安装（conda activate lty）
  2. 运行此脚本：python docs/test_diary_ui_data.py
  3. 观察动态对话框中的日记条目显示
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton
from src.gui.dynamics_dialog import DynamicsDialog


class MockResponse:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]


class MockNetworkClient:
    """返回模拟数据的 NetworkClient 桩。"""

    def get_dynamics(self, limit=40, cursor=None):
        now = "2026-07-31 12:00:00"
        return {
            "ok": True,
            "items": [
                {
                    "id": 1,
                    "author_type": "agent",
                    "author_name": "天依",
                    "author_id": "luotianyi",
                    "source_type": "diary",
                    "content": "2026-07-31 · 心情: 开心\n\n今天和主人聊了很多关于音乐的话题...",
                    "created_at": now,
                    "allow_comment": False,
                    "owner_user_id": "test_user",
                    "visibility": "private",
                },
                {
                    "id": 2,
                    "author_type": "agent",
                    "author_name": "天依",
                    "author_id": "luotianyi",
                    "source_type": "diary",
                    "content": "2026-07-30 · 心情: 温暖\n\n今天主人教了我一首新歌...",
                    "created_at": now,
                    "allow_comment": False,
                    "owner_user_id": "test_user",
                    "visibility": "private",
                },
                {
                    "id": 3,
                    "author_type": "user",
                    "author_name": "你",
                    "author_id": "test_user",
                    "source_type": "user_post",
                    "content": "今天天气真好，出去走了走，拍了一些照片。",
                    "created_at": now,
                    "allow_comment": True,
                },
                {
                    "id": 4,
                    "author_type": "agent",
                    "author_name": "天依",
                    "author_id": "luotianyi",
                    "source_type": "citywalk",
                    "content": "今天去了城市广场散步，看到了漂亮的喷泉。",
                    "created_at": now,
                    "allow_comment": True,
                },
                {
                    "id": 5,
                    "author_type": "agent",
                    "author_name": "天依",
                    "author_id": "luotianyi",
                    "source_type": "song_learned",
                    "content": "今天学会了一首新歌《千本樱》！",
                    "created_at": now,
                    "allow_comment": True,
                },
            ],
            "next_cursor": None,
            "has_more": False,
        }

    def get_dynamic_comments(self, dynamic_id, limit=200):
        return {
            "ok": True,
            "items": [
                {
                    "author_type": "user",
                    "author_name": "你",
                    "content": "好棒！",
                    "created_at": "2026-07-31 12:05:00",
                },
                {
                    "author_type": "agent",
                    "author_name": "天依",
                    "content": "谢谢主人～",
                    "created_at": "2026-07-31 12:06:00",
                },
            ],
        }

    def create_dynamic(self, content):
        return {"ok": True, "message": "发布成功"}

    def create_dynamic_comment(self, dynamic_id, content):
        return {"ok": True, "message": "评论成功"}

    def mark_dynamics_read(self):
        return {"ok": True}


def main():
    app = QApplication(sys.argv)
    client = MockNetworkClient()
    dialog = DynamicsDialog(client)
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
