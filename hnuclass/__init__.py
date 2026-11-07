# -*- coding: utf-8 -*-
"""HNU 程序设计小班课课件生成器。"""
import os
import sys

__version__ = "1.8.3"

# 免安装形态：把随包携带的 pylib 放上 sys.path，用户不必改环境变量。
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(os.path.dirname(_HERE), "pylib")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
