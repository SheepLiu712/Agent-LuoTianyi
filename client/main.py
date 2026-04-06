import sys
import os
import multiprocessing

# Determine execution path and set up environment
if getattr(sys, "frozen", False):
    # Running in a bundle (likely PyInstaller)
    # For OneDir: sys.executable is in the bundle dir.
    # Resources are strictly relative to the executable location (or we expect them there).
    cwd = os.path.dirname(os.path.abspath(sys.executable))
else:
    # Running in a normal python environment
    cwd = os.path.dirname(os.path.abspath(__file__))

# Change working directory to ensure relative paths work (crucial for config/res)
os.chdir(cwd)

# Ensure src is in path
if cwd not in sys.path:
    sys.path.append(cwd)

from PySide6.QtWidgets import QDialog

from src.utils.helpers import load_config
from src.gui import ui_init, MainWindow
from src.gui.binder import AgentBinder
from src.live2d import live2d
from src.network.network_client import NetworkClient
from src.message_process import MessageProcessor
from src.gui.login_dialog import LoginDialog


if __name__ == "__main__":
    multiprocessing.freeze_support()

    # 读取配置
    main_config_path = os.path.join(cwd, "config", "config.json")
    if not os.path.exists(main_config_path):
        print(f"Config not found at {main_config_path}")
    config = load_config(main_config_path)

    app = ui_init()

    # 创建网络客户端实例
    network_client = NetworkClient(
        base_url=config.get("base_url"),
        verify_ssl=bool(config.get("verify_ssl", True)),
    ) 
    # 创建消息处理器实例，并将网络客户端的消息监听器设置方法传入，以便消息处理器能接收网络消息
    message_processor = MessageProcessor(
        send_text_func = network_client.send_chat,
        send_image_func = network_client.send_image,
        send_typing_func = network_client.send_typing,
        message_listener_setter=network_client.network_set_message_listener
        ) 
    # 创建Binder实例，用于连接UI和网络层，传入网络客户端的相关回调方法
    binder = AgentBinder(
        send_text_callback = message_processor.send_text,
        send_image_callback = message_processor.send_image,
        send_typing_callback = message_processor.send_typing_event,
        play_local_tts_callback = message_processor.play_local_tts_by_uuid,
        stop_local_tts_callback = message_processor.stop_local_tts,
        set_volume_callback = message_processor.set_playback_volume,
        fetch_history_callback = network_client.get_history,
        set_model_callback = message_processor.set_model,
        auto_login_callback = network_client.auto_login,
        login_callback = network_client.login,
        register_callback = network_client.register,
    ) 
    # 将Binder的信号传入消息处理器，以便消息处理器能通过信号与UI交互
    message_processor.set_signals(
        response_signal=binder.emit_response_signal,
        update_bubble_signal=binder.emit_update_signal,
        agent_thinking_signal=binder.emit_agent_thinking_signal,
        local_tts_state_signal=binder.emit_local_tts_state_signal,
    ) 


    # 主运行逻辑
    ret = 0
    try:
        login_dialog = LoginDialog(binder)
        if not login_dialog.try_auto_login():
            if login_dialog.exec() != QDialog.DialogCode.Accepted:
                raise SystemExit("Login cancelled")
        print(f"Logged in as {network_client.user_id}")
        window = MainWindow(config["gui"], config["live2d"], binder)
        window.show()
        ret = app.exec()
    except SystemExit as e:
        print(f"Exiting: {e}")
        ret = 0
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        live2d.dispose()
        sys.exit(ret)
