import base64
import os
import sys

# 尝试导入 winsound，仅在 Windows 上可用
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False
    print("Warning: winsound module not found. Audio playback will be skipped (only available on Windows).")

def test_audio_codec_and_play():
    # 路径设定
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # example_audio.wav 在 client 根目录，即 tests 的上一级
    wav_path = os.path.join(os.path.dirname(current_dir), 'example_audio.wav')
    
    if not os.path.exists(wav_path):
        print(f"Error: {wav_path} not found.")
        print("Please ensure 'example_audio.wav' exists in the project root.")
        return

    print(f"Target Audio File: {wav_path}")

    # 1. 读取并编码为 Base64
    print("1. Reading file and encoding to Base64...")
    try:
        with open(wav_path, "rb") as audio_file:
            original_audio_data = audio_file.read()
            base64_audio = base64.b64encode(original_audio_data).decode('utf-8')
        
        print(f"   Success. Base64 string length: {len(base64_audio)}")
        # 打印前50个字符示意
        print(f"   Preview: {base64_audio[:50]}...")
    except Exception as e:
        print(f"   Failed to read or encode file: {e}")
        return

    # 2. 解码 Base64
    print("2. Decoding Base64 back to audio bytes...")
    try:
        decoded_audio_data = base64.b64decode(base64_audio)
        print(f"   Success. Decoded bytes length: {len(decoded_audio_data)}")
    except Exception as e:
        print(f"   Failed to decode base64: {e}")
        return

    # 验证数据完整性
    if original_audio_data == decoded_audio_data:
        print("   Data integrity verified: Decoded data matches original file.")
    else:
        print("   Warning: Decoded data does NOT match original file.")

    # 3. 播放解码后的音频
    print("3. Playing decoded audio...")
    
    if HAS_WINSOUND:
        try:
            # winsound.SND_MEMORY 指示第一个参数是内存中的数据
            # winsound.SND_NODEFAULT 如果找不到声音，不播放系统默认声音
            print("   Playing...")
            winsound.PlaySound(decoded_audio_data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
            print("   Playback finished.")
        except Exception as e:
            print(f"   Error playing sound: {e}")
    else:
        # 非 Windows 环境或者是需要跨平台时的备选方案 (需要安装 pyaudio)
        try:
            import pyaudio
            import wave
            import io
            
            print("   Using PyAudio for playback...")
            with wave.open(io.BytesIO(decoded_audio_data), 'rb') as wf:
                p = pyaudio.PyAudio()
                stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                                channels=wf.getnchannels(),
                                rate=wf.getframerate(),
                                output=True)
                
                chunk = 1024
                data = wf.readframes(chunk)
                while len(data) > 0:
                    stream.write(data)
                    data = wf.readframes(chunk)
                
                stream.stop_stream()
                stream.close()
                p.terminate()
            print("   Playback finished.")
        except ImportError:
            print("   'winsound' not available (not Windows?) and 'pyaudio' not installed.")
            print("   Cannot play audio directly.")
        except Exception as e:
            print(f"   Error utilizing PyAudio: {e}")

if __name__ == "__main__":
    test_audio_codec_and_play()
