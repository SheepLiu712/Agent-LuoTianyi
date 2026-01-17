import os
import sys
# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

if __name__ == "__main__":
    from src.utils.helpers import load_config
    from src.tts.tts_module_gsv import TTSModule
    config_path = r"./config/config.json"

    config = load_config(config_path)

    tts_config = config["tts"]

    tts_module = TTSModule(tts_config) 
    available_tones = tts_module.get_available_tones()

    # 一口气唱了这么多首歌，天依也有点累了呢。虽然还有很多想唱的歌、想说的话，但相聚的时光总会迎来尾声。今天的活动就到这里啦。请大家在工作人员的指挥引导下，注意安全，有序离场。期待下一次再见！拜拜啦！
    n = 1
    while n > 0: 
        output_path = tts_module.synthesize_speech("老A在美国有人",ref_audio="活力的参考音频")

        tts_module.play_audio(output_path)
        n -= 1