#!/usr/bin/env python3
"""
TinyClaude Web 启动脚本
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.server import run

if __name__ == "__main__":
    run()
