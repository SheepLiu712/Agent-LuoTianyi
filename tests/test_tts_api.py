import subprocess
import time
import os
import sys
import requests
import json

# Configuration
API_SCRIPT = "src/GPT_SoVITS/api_v2.py"
PORT = 9880
API_URL = f"http://127.0.0.1:{PORT}"
TTS_ENDPOINT = f"{API_URL}/tts"
CONTROL_ENDPOINT = f"{API_URL}/control"
OUTPUT_FILE = "test_output.wav"

# Find a reference audio
# Using the one found in the workspace
REF_AUDIO_CANDIDATES = [
    r"res\tts\reference_audio\活力的参考音频.wav",
]

def find_ref_audio():
    for path in REF_AUDIO_CANDIDATES:
        if os.path.exists(path):
            return path
    
    # Fallback search
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".wav") and "参考" in file:
                 return os.path.join(root, file)
    return None

def wait_for_server(url, timeout=120):
    start_time = time.time()
    print(f"Waiting for server at {url}...")
    while time.time() - start_time < timeout:
        try:
            # Check if server is responsive. 
            # Calling /control with a dummy command to avoid 400 error logs on server side.
            response = requests.get(f"{url}/control", params={"command": "health_check"}, timeout=1)
            if response.status_code in [200, 400, 422]:
                return True
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            print(f"Polling error: {e}")
        
        time.sleep(2)
        print(".", end="", flush=True)
    return False

def main():
    ref_audio = find_ref_audio()
    if not ref_audio:
        print("Error: No reference audio found. Please ensure a .wav file exists.")
        return

    print(f"Using reference audio: {ref_audio}")

    # Start the server
    print("Starting API server...")
    # Use the same python interpreter
    server_process = subprocess.Popen([sys.executable, API_SCRIPT], cwd=os.getcwd())

    try:
        if wait_for_server(API_URL):
            print("\nServer is ready.")
            
            # Prepare request
            payload = {
                "text": "你好，这是一个测试音频，用于验证接口是否正常工作。",
                "text_lang": "zh",
                "ref_audio_path": ref_audio,
                "prompt_lang": "zh",
                "prompt_text": "那，我们抓紧时间，继续唱起来吧！进入下一首！", # Optional, but prompt_lang is required
                "text_split_method": "cut5",
                "batch_size": 1,
                "media_type": "wav",
                "streaming_mode": False
            }

            print("Sending TTS request...")
            try:
                response = requests.post(TTS_ENDPOINT, json=payload)

                if response.status_code == 200:
                    with open(OUTPUT_FILE, "wb") as f:
                        f.write(response.content)
                    print(f"Audio saved to {OUTPUT_FILE}")
                    
                    # Play audio
                    print("Playing audio...")
                    if sys.platform == "win32":
                        import winsound
                        # 使用 winsound 直接播放，不打开外部播放器
                        winsound.PlaySound(response.content, winsound.SND_MEMORY)
                    else:
                        print("Auto-play not supported on this platform.")
                else:
                    print(f"Error: {response.status_code}")
                    print(response.text)
            except Exception as req_err:
                print(f"Request failed: {req_err}")

        else:
            print("\nServer failed to start in time.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

    finally:
        print("Stopping server...")
        # Try to stop gracefully via API
        try:
            requests.get(f"{API_URL}/control", params={"command": "exit"}, timeout=1)
        except:
            pass
        
        # Force kill if needed
        if server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
        print("Server stopped.")

if __name__ == "__main__":
    main()
