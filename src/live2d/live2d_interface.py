import live2d.v3 as live2d
from typing import Optional, List, Dict, Any


class Live2dModel():
    def __init__(self, live2d_config: Dict[str, Any]) -> None:
        self.config = live2d_config
        self.model_config: Dict[str, Any] = self.config["model"]
        self.expression_projection: Dict[str, str] = self.config.get("expression_projection", {})

    
    def model_init(self) -> None:
        assert live2d.LIVE2D_VERSION == 3, "仅支持 live2d v3"
        live2d.glInit()
        self.model_path: str = self.model_config["model_path"]
        self.model: Optional[live2d.LAppModel] = live2d.LAppModel()
        self.model.LoadModelJson(self.model_path)
        self._init_expression()
        self._init_motion()
        self._init_hit_areas()
        self.offset = self.model_config.get("offset", [0, 0])

        # 自动眨眼和呼吸
        self.model.SetAutoBlinkEnable(True)
        self.model.SetAutoBreathEnable(True)
        self.model.SetOffset(self.offset[0], self.offset[1])

    # Belows are init functions
    def _init_expression(self) -> None:
        # 处理表情数据
        self.expression_list: List[str] = self.model.GetExpressionIds()
        default_expression = self.model_config.get("default_expression", None)
        # get the index of default expression
        if default_expression and default_expression in self.expression_list:
            self.default_expression_index: int = self.expression_list.index(default_expression)
        else:
            self.default_expression_index: int = 0
        self.now_expression: int = self.default_expression_index
        self.expression_num: int = len(self.expression_list)
        self.model.SetExpression(self.expression_list[self.now_expression])
    
    def _init_motion(self) -> None:
        # 处理动作数据
        self.motion_group_names: List[str] = [group_name for group_name in self.model.GetMotionGroups().keys()]
    
    def _init_hit_areas(self) -> None:
        model_json_path: str = self.model_config["model_path"]
        with open(model_json_path, "r", encoding="utf-8") as f:
            import json
            model_json: Dict[str, Any] = json.load(f)
            self.hit_areas: List[Dict[str, str]] = model_json.get("HitAreas", [])
    
    # Belows are custom methods
    def set_next_expression(self) -> None:
        self.now_expression += 1
        if self.now_expression >= self.expression_num:
            self.now_expression = 0
        self.SetExpression(self.expression_list[self.now_expression])

    # Since LAppModel is not an acceptable base type in Python, we need to wrap its methods
    def Update(self) -> None:
        if self.model:
            self.model.Update()

    def Draw(self) -> None:
        if self.model:
            self.model.Draw()

    def Resize(self, w: int, h: int) -> None:
        if self.model:
            self.model.Resize(w, h)

    def SetExpression(self, expression_id: str) -> None:
        if self.model:
            self.model.SetExpression(expression_id)

    def HitTest(self, area_name: str, x: float, y: float) -> bool:
        if self.model:
            return self.model.HitTest(area_name, x, y)
        return False
    
    def Drag(self, x: float, y: float) -> None:
        if self.model:
            self.model.Drag(x, y)

    def SetAutoBlinkEnable(self, enable: bool) -> None:
        if self.model:
            self.model.SetAutoBlinkEnable(enable)

    def SetAutoBreathEnable(self, enable: bool) -> None:
        if self.model:
            self.model.SetAutoBreathEnable(enable)

    def Rotate(self, degrees:float) -> None:
        if self.model:
            self.model.Rotate(degrees)

    def IsMotionFinished(self) -> bool:
        """
        当前正在播放的动作是否已经结束
        :return:
        """
        if self.model:
            return self.model.IsMotionFinished() 
        return True
    
    def SetScale(self, scale: float) -> None:
        if self.model:
            self.model.SetScale(scale)
    
    def SetOffset(self, x: float, y: float) -> None:
        if self.model:
            self.model.SetOffset(x, y)

    def StartMotion(self, group: str | Any, no: int | Any, priority: int | Any, onStartMotionHandler=None,
                    onFinishMotionHandler=None) -> None:
        """
        Start a specific motion for the model.
        
        :param group: The group name of the motion.
        :param no: The motion number within the group.
        :param priority: Priority of the motion. Higher priority motions can interrupt lower priority ones.
        :param onStartMotionHandler: Optional callback function that gets called when the motion starts.
        :param onFinishMotionHandler: Optional callback function that gets called when the motion finishes.
        """
        if self.model:
            self.model.StartMotion(group, no, priority, onStartMotionHandler, onFinishMotionHandler)

    def get_available_expressions(self) -> List[str]:
        """
        获取模型可用的表情列表
        :return: 表情ID列表
        """
        return list(self.config["expression_projection"].keys())
    
    def set_expression_by_cmd(self, cmd_name: str) -> None:
        """
        根据表情名称设置表情
        :param expression_name: 表情名称
        """
        if cmd_name not in self.expression_projection:
            raise ValueError(f"表情名称 {cmd_name} 不存在于模型配置中")
        expression_name = self.expression_projection.get(cmd_name, None)
        if expression_name not in self.expression_list:
            raise ValueError(f"表情名称 {cmd_name} 未映射到具体表情ID")
        self.SetExpression(expression_name)