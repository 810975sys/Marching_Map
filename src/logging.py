# logging_info.py
import logging
import sys
from pathlib import Path
from src.app_settings_dock import _PROJECT_ROOT

def setup_logging():
    """配置全局日志系统，在程序入口调用一次即可。"""
    LOG_FILE = _PROJECT_ROOT / "marching_map.log"
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 文件 Handler
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    root_logger.addHandler(file_handler)
    