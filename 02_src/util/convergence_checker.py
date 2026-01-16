"""収束判定ロジック

設計意図:
- 最適化の停止条件を判定する専用モジュール
- 統計的手法で収束を判定（単純な閾値ではなく、連続的な改善率チェック）
- Optunaのstudyオブジェクトに依存するが、ロジック自体は汎用的
"""
from typing import Tuple


def check_convergence(study, patience: int, min_improvement: float) -> Tuple[bool, str]:
    """収束判定を行う

    設計意図:
    - patience回連続で改善が小さい場合に収束と判定
    - 無限大やNoneの値を除外して頑健性を向上
    - 詳細なメッセージを返すことでデバッグを容易に

    Args:
        study: Optunaのstudyオブジェクト
        patience: 連続して改善が小さい回数の閾値
        min_improvement: 改善率の最小値（これ未満なら「小さい改善」とみなす）

    Returns:
        (収束したか, 詳細メッセージ)

    アルゴリズム:
    1. 最近のpatience+10個の有効な値を取得
    2. 各時点でのベスト値を計算
    3. 10期間ごとの改善率を計算
    4. patience回連続で改善率がmin_improvement未満なら収束
    """
    # 十分なトライアル数が必要（設計意図: 統計的に意味のある判定のため）
    if len(study.trials) < patience + 10:
        return False, f"トライアル数不足 ({len(study.trials)}/{patience + 10})"

    # 有効なトライアル（無限大でない値）を取得
    valid_trials = [trial for trial in study.trials
                   if trial.value is not None and trial.value != float('inf')]

    if len(valid_trials) < patience + 10:
        return False, f"有効なトライアル数不足 ({len(valid_trials)}/{patience + 10})"

    # 最近のpatience+10個の有効な値を取得
    recent_values = []
    for trial in reversed(study.trials):
        if trial.value is not None and trial.value != float('inf'):
            recent_values.append(trial.value)
        if len(recent_values) >= patience + 10:
            break

    recent_values.reverse()  # 古い順に戻す

    # 各時点でのベスト値を計算（設計意図: 累積的な改善を追跡）
    best_so_far = []
    current_best = float('inf')
    for value in recent_values:
        current_best = min(current_best, value)
        best_so_far.append(current_best)

    # 連続して改善が小さい回数をカウント
    small_improvement_count = 0

    for i in range(10, len(best_so_far)):
        # i-10時点のベスト値と現在(i時点)のベスト値を比較
        old_best = best_so_far[i-10]
        current_best = best_so_far[i]

        # 改善率を計算（設計意図: 絶対値ではなく相対値で判定）
        if abs(old_best) > 1e-10:  # ゼロ除算回避
            improvement_rate = abs(current_best - old_best) / abs(old_best)
        else:
            improvement_rate = abs(current_best - old_best)

        # 改善が小さい場合
        if improvement_rate < min_improvement:
            small_improvement_count += 1
        else:
            small_improvement_count = 0  # 連続カウントをリセット

        # patience回連続で小さい改善の場合は収束
        if small_improvement_count >= patience:
            total_improvement = (
                abs(best_so_far[-1] - best_so_far[-(patience+1)]) / abs(best_so_far[-(patience+1)])
                if abs(best_so_far[-(patience+1)]) > 1e-10
                else abs(best_so_far[-1] - best_so_far[-(patience+1)])
            )
            return True, (
                f"収束判定: 連続{patience}期間で改善率{total_improvement*100:.4f}% "
                f"< 閾値{min_improvement*100:.2f}%"
            )

    # 継続中の場合、最新の改善率を表示
    if len(best_so_far) >= 11:
        latest_improvement = (
            abs(best_so_far[-1] - best_so_far[-11]) / abs(best_so_far[-11])
            if abs(best_so_far[-11]) > 1e-10
            else abs(best_so_far[-1] - best_so_far[-11])
        )
        return False, (
            f"継続中: 最新10期間の改善率{latest_improvement*100:.4f}% "
            f"(連続小改善回数: {small_improvement_count}/{patience})"
        )

    return False, "継続中: 改善率計算には十分なデータが不足"
