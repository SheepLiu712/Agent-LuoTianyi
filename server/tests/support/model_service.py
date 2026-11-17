"""让接口测试通过模型服务注册假的模型。"""

from types import SimpleNamespace


def model_service(models):
    return SimpleNamespace(register_llm_module=lambda name, config: models[config["test_model"]])


def make_call_summary(models):
    from src.agent.skills.cognitive.call_settlement import CallSummarySkill

    service = SimpleNamespace(register_llm_module=lambda name, config: models[name.rsplit(".", 1)[-1]])
    return CallSummarySkill({"llm_module": {}} if models else {}, llm_service=service, characters=models)
