import os
import time
import requests
import multiprocessing
import atexit
import sys
from typing import Optional
from ..utils.logger import get_logger

# Helper function to run server process
def run_server_silent(config_path, host, port):
    """Wrapper to run the server with stdout/stderr redirected to devnull."""
    # sys.stderr = open(os.devnull, 'w')
    # Use standard import inside process to avoid pickling issues
    from src.GPT_SoVITS.api_v2 import run_server
    run_server(config_path, host, port)

class TTSServer:
    """
    Manages the lifecycle of the GPT-SoVITS server process.
    """
    def __init__(self, config_path: str, host: str = "127.0.0.1", port: int = 9880):
        self.config_path = config_path
        self.host = host
        self.port = port
        self.logger = get_logger("TTSServer")
        self.server_process: Optional[multiprocessing.Process] = None
        self.api_url = f"http://{host}:{port}"

    def start(self):
        """Starts the TTS server process if not already running."""
        self._kill_process_on_port(self.port)

        if not os.path.exists(self.config_path):
            self.logger.error(f"Config file not found at {self.config_path}")
            raise FileNotFoundError(f"Config file not found at {self.config_path}")
        
        self.logger.info("Starting GPT-SoVITS server in a separate process...")
        
        self.server_process = multiprocessing.Process(
            target=run_server_silent,
            args=(self.config_path, self.host, self.port),
            daemon=True
        )
        self.server_process.start()
        
        if not self._wait_for_server():
            self.logger.error("Failed to start GPT-SoVITS server.")
            if self.server_process.is_alive():
                self.server_process.terminate()
            raise RuntimeError("Failed to start GPT-SoVITS server")
        
        self.logger.info(f"GPT-SoVITS server started successfully at {self.api_url}")
        
        # Ensure cleanup on main process exit
        atexit.register(self.stop)

    def stop(self):
        """Stops the TTS server process."""
        if self.server_process:
            self.logger.info("Stopping GPT-SoVITS server...")
            try:
                # Try graceful shutdown via API
                requests.get(f"{self.api_url}/control", params={"command": "exit"}, timeout=1)
            except:
                pass
            
            if self.server_process.is_alive():
                self.server_process.join(timeout=5)
                if self.server_process.is_alive():
                    self.logger.warning("GPT-SoVITS server did not exit gracefully, terminating...")
                    self.server_process.terminate()
                    self.server_process.join()
            
            self.server_process = None
            self.logger.info("GPT-SoVITS server stopped.")

    def get_api_url(self) -> str:
        return self.api_url

    def _kill_process_on_port(self, port):
        """Kill any process listening on the specified port."""
        try:
            import psutil
            for proc in psutil.process_iter():
                try:
                    for conn in proc.net_connections():
                        if conn.laddr.port == port:
                            self.logger.warning(f"Port {port} is in use by process {proc.pid} ({proc.name()}). Killing it...")
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except ImportError:
            self.logger.error("psutil not installed, cannot kill process on port.")
        except Exception as e:
            self.logger.error(f"Error killing process on port {port}: {e}")

    def _wait_for_server(self, timeout=600) -> bool:
        """Waits until the server is responsive."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.api_url}/control", params={"command": "health_check"}, timeout=1)
                if response.status_code in [200, 400, 422]: 
                    return True
            except requests.exceptions.ConnectionError:
                pass
            except Exception as e:
                self.logger.debug(f"Polling error: {e}")
            
            if self.server_process and not self.server_process.is_alive():
                self.logger.error("Server process died unexpectedly.")
                return False

            time.sleep(1)
        return False
