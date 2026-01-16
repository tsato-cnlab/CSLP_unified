#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可視化プラグインの基盤モジュール

新しい可視化を追加するには:
1. このディレクトリに新しい.pyファイルを作成
2. @register_visualizerデコレータを使用して関数を登録
3. visualization_config.yamlで有効化

例:
    @register_visualizer("my_chart")
    def plot_my_chart(result_file, save_dir, **context):
        # result_file: pklファイルのPath
        # save_dir: 保存先ディレクトリのPath
        # context: study, best_trial_number等の追加情報
        pass
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Any
import functools

# 登録された可視化関数のレジストリ
_VISUALIZER_REGISTRY: dict[str, "VisualizerInfo"] = {}


@dataclass
class VisualizerInfo:
    """可視化関数の情報"""
    name: str
    func: Callable
    description: str = ""
    output_file: str = ""  # 出力ファイル名（拡張子なし）
    requires_study: bool = False  # Optuna Studyが必要か
    requires_result_file: bool = True  # pklファイルが必要か
    priority: int = 100  # 実行優先度（小さい方が先）


def register_visualizer(
    name: str,
    description: str = "",
    output_file: Optional[str] = None,
    requires_study: bool = False,
    requires_result_file: bool = True,
    priority: int = 100,
):
    """可視化関数を登録するデコレータ

    Args:
        name: 可視化の識別名（設定ファイルで使用）
        description: 説明
        output_file: 出力ファイル名（拡張子なし、省略時はnameを使用）
        requires_study: Optuna Studyが必要か
        requires_result_file: pklファイルが必要か
        priority: 実行優先度（小さい方が先）

    Example:
        @register_visualizer("waiting_time", output_file="waiting_time_histogram")
        def plot_waiting_time(result_file, save_dir, **context):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # レジストリに登録
        _VISUALIZER_REGISTRY[name] = VisualizerInfo(
            name=name,
            func=wrapper,
            description=description,
            output_file=output_file or name,
            requires_study=requires_study,
            requires_result_file=requires_result_file,
            priority=priority,
        )

        return wrapper
    return decorator


def get_visualizer(name: str) -> Optional[VisualizerInfo]:
    """名前で可視化関数を取得"""
    return _VISUALIZER_REGISTRY.get(name)


def get_all_visualizers() -> dict[str, VisualizerInfo]:
    """登録された全ての可視化関数を取得"""
    return _VISUALIZER_REGISTRY.copy()


def get_visualizers_sorted() -> list[VisualizerInfo]:
    """優先度順にソートされた可視化関数のリストを取得"""
    return sorted(_VISUALIZER_REGISTRY.values(), key=lambda v: v.priority)
