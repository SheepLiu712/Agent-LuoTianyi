"""
用户偏好管理器 - 负责管理用户自定义内容
包括：重要日期提醒、相处模式设置
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional


class UserPreferencesManager:
    """管理用户偏好设置"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            # 默认路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, "..", "..", "config", "user_preferences.json")
            config_path = os.path.normpath(config_path)
        
        self.config_path = config_path
        self.preferences = self._load_preferences()
    
    def _load_preferences(self) -> Dict[str, Any]:
        """加载用户偏好设置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return self._create_default_preferences()
        except Exception as e:
            print(f"加载用户偏好失败: {e}")
            return self._create_default_preferences()
    
    def _create_default_preferences(self) -> Dict[str, Any]:
        """创建默认偏好设置"""
        default = {
            "important_dates": [],
            "relationship_mode": {
                "relationship": "朋友",
                "speaking_style": "友好温和",
                "personality_traits": ["温柔", "耐心"],
                "custom_context": ""
            },
            "reminder_settings": {
                "enable_reminders": True,
                "reminder_time": "09:00",
                "check_interval_hours": 1
            }
        }
        self._save_preferences(default)
        return default
    
    def _save_preferences(self, preferences: Dict[str, Any] = None):
        """保存偏好设置到文件"""
        try:
            if preferences is None:
                preferences = self.preferences
            
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(preferences, f, ensure_ascii=False, indent=2)
            self.preferences = preferences
            return True
        except Exception as e:
            print(f"保存用户偏好失败: {e}")
            return False
    
    def save(self):
        """保存当前偏好设置"""
        return self._save_preferences()
    
    # ========== 重要日期管理 ==========
    
    def add_important_date(self, name: str, date: str, date_type: str = "other", 
                           message: str = "", enabled: bool = True) -> bool:
        """
        添加重要日期
        :param name: 事件名称（如"我的生日"）
        :param date: 日期 (YYYY-MM-DD 格式，如果是生日可以只有MM-DD)
        :param date_type: 类型 - "birthday", "anniversary", "schedule", "other"
        :param message: 自定义提醒消息
        :param enabled: 是否启用提醒
        :return: 是否成功
        """
        try:
            new_date = {
                "id": len(self.preferences["important_dates"]) + 1,
                "name": name,
                "date": date,
                "type": date_type,
                "message": message if message else f"今天是{name}，想你啦！",
                "enabled": enabled
            }
            self.preferences["important_dates"].append(new_date)
            return self._save_preferences()
        except Exception as e:
            print(f"添加重要日期失败: {e}")
            return False
    
    def remove_important_date(self, date_id: int) -> bool:
        """删除重要日期"""
        try:
            self.preferences["important_dates"] = [
                d for d in self.preferences["important_dates"] if d.get("id") != date_id
            ]
            return self._save_preferences()
        except Exception as e:
            print(f"删除重要日期失败: {e}")
            return False
    
    def get_important_dates(self) -> List[Dict[str, Any]]:
        """获取所有重要日期"""
        return self.preferences.get("important_dates", [])
    
    def check_today_dates(self) -> List[Dict[str, Any]]:
        """
        检查今天是否有重要日期
        :return: 今天的重要日期列表
        """
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        today_month_day = today.strftime("%m-%d")
        
        matched_dates = []
        for date_info in self.preferences.get("important_dates", []):
            if not date_info.get("enabled", True):
                continue
            
            date_str = date_info.get("date", "")
            # 匹配完整日期 YYYY-MM-DD 或 月日 MM-DD
            if date_str == today_str or date_str == today_month_day:
                matched_dates.append(date_info)
        
        return matched_dates
    
    # ========== 相处模式管理 ==========
    
    def set_relationship_mode(self, relationship: str = None, speaking_style: str = None,
                             personality_traits: List[str] = None, custom_context: str = None):
        """设置相处模式"""
        try:
            mode = self.preferences.get("relationship_mode", {})
            
            if relationship is not None:
                mode["relationship"] = relationship
            if speaking_style is not None:
                mode["speaking_style"] = speaking_style
            if personality_traits is not None:
                mode["personality_traits"] = personality_traits
            if custom_context is not None:
                mode["custom_context"] = custom_context
            
            self.preferences["relationship_mode"] = mode
            return self._save_preferences()
        except Exception as e:
            print(f"设置相处模式失败: {e}")
            return False
    
    def get_relationship_context(self) -> str:
        """
        获取相处模式的上下文描述，用于添加到AI回复的上下文
        :return: 上下文字符串
        """
        mode = self.preferences.get("relationship_mode", {})
        relationship = mode.get("relationship", "朋友")
        speaking_style = mode.get("speaking_style", "友好温和")
        personality_traits = mode.get("personality_traits", [])
        custom_context = mode.get("custom_context", "")
        
        context_parts = [
            f"你和用户的关系是：{relationship}。",
            f"你的表达风格应该是：{speaking_style}。",
        ]
        
        if personality_traits:
            traits_str = "、".join(personality_traits)
            context_parts.append(f"你的性格特点：{traits_str}。")
        
        if custom_context:
            context_parts.append(custom_context)
        
        return "\n".join(context_parts)
    
    def get_relationship_mode(self) -> Dict[str, Any]:
        """获取当前相处模式设置"""
        return self.preferences.get("relationship_mode", {})
    
    # ========== 提醒设置管理 ==========
    
    def set_reminder_settings(self, enable_reminders: bool = None, 
                             reminder_time: str = None, 
                             check_interval_hours: int = None):
        """设置提醒参数"""
        try:
            settings = self.preferences.get("reminder_settings", {})
            
            if enable_reminders is not None:
                settings["enable_reminders"] = enable_reminders
            if reminder_time is not None:
                settings["reminder_time"] = reminder_time
            if check_interval_hours is not None:
                settings["check_interval_hours"] = check_interval_hours
            
            self.preferences["reminder_settings"] = settings
            return self._save_preferences()
        except Exception as e:
            print(f"设置提醒参数失败: {e}")
            return False
    
    def get_reminder_settings(self) -> Dict[str, Any]:
        """获取提醒设置"""
        return self.preferences.get("reminder_settings", {})
