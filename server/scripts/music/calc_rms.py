import os
import sys
from pydub import AudioSegment
import math

def calculate_rms(file_path):
    print(f"正在处理文件: {file_path}")
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
        return

    try:
        audio = AudioSegment.from_file(file_path)
        
        # pydub 直接提供了 rms 属性 (root mean square)
        rms = audio.rms
        
        # 也可以转换为 dBFS (decibels relative to full scale)
        print(type(audio))
        dbfs = audio.dBFS
        
        print("-" * 30)
        print(f"RMS (振幅绝对值): {rms}")
        print(f"dBFS (相对满刻度分贝): {dbfs:.2f} dB")
        print(f"最大振幅 (Max Amplitude): {audio.max}")
        print("-" * 30)
        
    except Exception as e:
        print(f"处理文件时发生错误: {e}")

if __name__ == "__main__":
    # 优先查找 locations
    # 1. 命令行参数
    # 2. data/tts_output 下
    # 3. server 根目录下
    # 4. 当前目录下
    
    target_filename = "temp_output.wav"
    
    # 获取脚本所在目录的上一级两层 (server/scripts/music -> server/)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    
    potential_paths = [
        os.path.join(project_root, "data", "tts_output", target_filename),
        os.path.join(project_root, target_filename),
        os.path.join(os.getcwd(), target_filename)
    ]
    
    found_path = None
    if len(sys.argv) > 1:
        custom_path = sys.argv[1]
        if os.path.exists(custom_path):
            found_path = custom_path
    
    if not found_path:
        for p in potential_paths:
            if os.path.exists(p):
                found_path = p
                break
    
    if found_path:
        calculate_rms(found_path)
    else:
        print(f"未找到文件: {target_filename}")
        print("请检查文件位置或作为参数传入路径。")
