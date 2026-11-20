"""AgentLuo 版本部署统一命令入口。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "release"))
from cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
