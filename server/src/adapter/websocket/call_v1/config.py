"""通话协议接入配置。"""


def parse_call_transport_enabled(config: dict) -> bool:
    """严格读取通话启用开关；启用不代表运行能力已经就绪。"""
    section = config.get("call_transport", {})
    if not isinstance(section, dict):
        raise ValueError("call_transport must be an object")
    value = section.get("enabled", False)
    if type(value) is not bool:
        raise ValueError("call_transport.enabled must be a boolean")
    return value
