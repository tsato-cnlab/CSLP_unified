#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可視化プラグインパッケージ

このパッケージ内の全ての可視化モジュールを自動的に読み込み、
register_visualizerデコレータで登録された関数を利用可能にする。
"""

import importlib
import pkgutil
from pathlib import Path

# 基盤をエクスポート
from .base import (
    register_visualizer,
    get_visualizer,
    get_all_visualizers,
    get_visualizers_sorted,
    VisualizerInfo,
)

# このパッケージ内の全モジュールを自動インポート
_package_dir = Path(__file__).parent

for _, module_name, _ in pkgutil.iter_modules([str(_package_dir)]):
    if module_name != "base":  # base.pyは既にインポート済み
        importlib.import_module(f".{module_name}", package=__name__)


__all__ = [
    "register_visualizer",
    "get_visualizer",
    "get_all_visualizers",
    "get_visualizers_sorted",
    "VisualizerInfo",
]
