"""让测试能以项目根为导入基准运行"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
