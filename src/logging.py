# logging_info.py
import logging
import sys
from pathlib import Path

def setup_logging():
    """配置全局日志系统，在程序入口调用一次即可。"""
    if getattr(sys, 'frozen', False):
        # 打包后，exe 所在目录
        log_dir = Path(sys.executable).parent
        # 你也可以选择直接放在 exe 目录下，或者建一个子文件夹（推荐子文件夹更整洁）
        # log_dir = exe_dir   # 如果你想直接放在 exe 目录，改成 log_dir = exe_dir
    else:
        # 开发环境：使用项目根目录（需要导入 _PROJECT_ROOT）
        from src.app_settings_dock import _PROJECT_ROOT
        log_dir = _PROJECT_ROOT
    log_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = log_dir  / "marching_map.log"
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 文件 Handler
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    root_logger.addHandler(file_handler)
    