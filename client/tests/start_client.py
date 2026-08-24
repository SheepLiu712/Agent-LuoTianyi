import sys
import os
import time

# Ensure src is in path
cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.append(cwd)

from src.utils.helpers import load_config
from src.gui import ui_init, MainWindow
from src.gui.binder import AgentBinder
from src.live2d import live2d

def dummy_hear_callback(text: str):
    print(f"Heard: {text}")
    # Simulating a response
    binder.start_thinking()
    
    # Simulate Async response
    import threading
    def respond():
        time.sleep(1) # Thinking
        binder.response_signal.emit("I heard you: " + text)
        binder.stop_thinking()
        
    threading.Thread(target=respond).start()

def dummy_history_callback(count, end_index):
    return [], 0

if __name__ == "__main__":
    main_config_path = os.path.join(cwd, "config", "config.json")
    if not os.path.exists(main_config_path):
        print(f"Config not found at {main_config_path}")
        # Try to use template if config doesn't exist (it should)
        
    config = load_config(main_config_path)

    app = ui_init()
    
    binder = AgentBinder(hear_callback=dummy_hear_callback, history_callback=dummy_history_callback)
    
    # config.json contains "gui", "live2d", etc.
    try:
        window = MainWindow(config["gui"], config["live2d"], binder)
        window.show()
    except Exception as e:
        print(f"Error creating MainWindow: {e}")
        import traceback
        traceback.print_exc()
        live2d.dispose()
        sys.exit(1)

    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)
