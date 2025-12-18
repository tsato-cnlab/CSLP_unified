"""ファイル管理とクリーンアップ機能

設計意図:
- 最適化結果ファイルの管理を一元化
- 並列処理に対応したファイル操作（ロックとバッチ処理）
- ディスク容量節約のため、不要なファイルを自動削除
"""
import os
import shutil
import pickle
from pathlib import Path
from multiprocessing import Pool
from typing import List, Dict, Optional
from tqdm import tqdm


def manage_pkl_files_after_optimization(study, save_dir: str, keep_best_n: int = 30):
    """最適化完了後のpklファイル管理（並列処理対応版）

    設計意図:
    - ベストNトライアルのみを保持してディスク容量を節約
    - 並列処理でファイル削除を高速化
    - 進捗バーでユーザーに状況を可視化

    Args:
        study: Optunaのstudyオブジェクト
        save_dir: 結果保存ディレクトリ
        keep_best_n: 保持するベストトライアル数
    """
    print(f"\n🗑️  最適化完了後のファイル整理を開始...")
    print(f"📊 総トライアル数: {len(study.trials)}")

    # ベストNトライアルのファイル名を取得
    best_trials = sorted(study.best_trials, key=lambda t: t.value)[:keep_best_n]
    best_trial_numbers = {trial.number for trial in best_trials}

    print(f"🏆 ベスト{keep_best_n}トライアルを保持:")
    for i, trial in enumerate(best_trials[:5], 1):
        print(f"  {i}. Trial {trial.number}: {trial.value:.2f}万円")
    if len(best_trials) > 5:
        print(f"  ... (他{len(best_trials)-5}件)")

    # 保存ディレクトリ内の全pklファイルを取得
    all_pkl_files = list(Path(save_dir).glob("*.pkl"))
    print(f"📁 総ファイル数: {len(all_pkl_files)}個")

    # 削除対象のファイルをリストアップ
    files_to_delete = []
    files_to_keep = []

    for pkl_file in all_pkl_files:
        # ファイル名からトライアル番号を抽出（設計意図: 柔軟なファイル名パターンに対応）
        trial_number = _extract_trial_number_from_filename(pkl_file.name)

        if trial_number is not None:
            if trial_number in best_trial_numbers:
                files_to_keep.append(pkl_file)
            else:
                files_to_delete.append(pkl_file)
        else:
            # トライアル番号が不明なファイルは保持（設計意図: 安全側に倒す）
            files_to_keep.append(pkl_file)

    print(f"✅ 保持: {len(files_to_keep)}個, 削除: {len(files_to_delete)}個")

    if len(files_to_delete) == 0:
        print("✨ 削除対象ファイルなし")
        return

    # 並列処理でファイル削除（設計意図: 大量ファイルの削除を高速化）
    batch_size = 100
    deleted_count = 0

    for i in range(0, len(files_to_delete), batch_size):
        batch = files_to_delete[i:i+batch_size]

        # バッチごとに削除
        with Pool(processes=min(4, len(batch))) as pool:
            results = list(tqdm(
                pool.imap(_delete_file_safe, batch),
                total=len(batch),
                desc=f"🗑️  削除中 (バッチ {i//batch_size + 1})",
                unit="file"
            ))

        deleted_count += sum(results)

    print(f"✅ ファイル整理完了: {deleted_count}個のファイルを削除")

    # ディスク容量の節約効果を表示（設計意図: ユーザーに作業の価値を示す）
    avg_file_size_mb = sum(f.stat().st_size for f in files_to_keep) / len(files_to_keep) / 1024 / 1024
    saved_space_mb = deleted_count * avg_file_size_mb
    print(f"💾 推定節約ディスク容量: {saved_space_mb:.1f} MB")


def _extract_trial_number_from_filename(filename: str) -> Optional[int]:
    """ファイル名からトライアル番号を抽出（内部関数）

    設計意図:
    - 様々なファイル名パターンに対応
    - 正規表現を使わずシンプルな文字列操作で実装（高速化）

    対応パターン:
    - trial_123.pkl
    - trial_456_combo_1_failure_2.pkl
    - trial_789_normal.pkl
    """
    try:
        # "trial_"の後の数字を抽出
        if "trial_" in filename:
            parts = filename.split("trial_")[1].split("_")[0].split(".")[0]
            return int(parts)
    except (ValueError, IndexError):
        pass

    return None


def _delete_file_safe(file_path: Path) -> bool:
    """ファイルを安全に削除（内部関数、並列処理用）

    設計意図:
    - エラーが発生しても他のファイル削除は続行
    - 削除成功/失敗をboolで返す（カウント用）
    """
    try:
        file_path.unlink()
        return True
    except Exception:
        return False


def cleanup_worker_environments(max_workers: int = 100):
    """ワーカー環境をクリーンアップ

    設計意図:
    - 並列最適化で作成された一時ディレクトリを削除
    - シミュレーション結果を削除してディスク容量を節約
    - エラーが発生しても処理を継続（頑健性）

    Args:
        max_workers: 削除対象のワーカー数の上限
    """
    print(f"\n🧹 ワーカー環境のクリーンアップ開始...")

    from src.util.path_manager import get_paths

    deleted_dirs = 0
    failed_dirs = []

    for worker_id in tqdm(range(1, max_workers + 1), desc="🗑️  ワーカーディレクトリ削除中"):
        try:
            paths = get_paths(worker_id)
            shikata_dir = Path(paths["shikata"])

            if shikata_dir.exists():
                # ematesとinstのみ削除（設計意図: opendssディレクトリは保持）
                result_dir = shikata_dir
                if result_dir.exists():
                    shutil.rmtree(result_dir)
                    deleted_dirs += 1
        except Exception as e:
            failed_dirs.append((worker_id, str(e)))

    print(f"✅ クリーンアップ完了: {deleted_dirs}個のディレクトリを削除")

    if failed_dirs:
        print(f"⚠️  削除失敗: {len(failed_dirs)}個")
        for worker_id, error in failed_dirs[:5]:
            print(f"  Worker {worker_id}: {error}")


def save_optimization_summary(study, save_dir: str, failure_config: dict = None):
    """最適化結果のサマリーを保存

    設計意図:
    - 最適化結果を人間が読みやすい形式で保存
    - 確率的最適化の詳細情報も記録
    - レポート生成を自動化
    """
    summary_path = Path(save_dir) / "optimization_summary.txt"

    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("最適化結果サマリー\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"総トライアル数: {len(study.trials)}\n")
        f.write(f"最適値: {study.best_value:.2f} 万円\n")
        f.write(f"最適トライアル番号: {study.best_trial.number}\n\n")

        # ベストトライアルの詳細
        best_trial = study.best_trial
        f.write("--- ベストトライアル詳細 ---\n")

        if hasattr(best_trial, 'user_attrs') and best_trial.user_attrs:
            for key, value in best_trial.user_attrs.items():
                f.write(f"{key}: {value}\n")

        f.write("\n--- パラメータ ---\n")
        for key, value in best_trial.params.items():
            f.write(f"{key}: {value}\n")

        if failure_config:
            f.write("\n--- 故障シナリオ設定 ---\n")
            for key, value in failure_config.items():
                f.write(f"{key}: {value}\n")

    print(f"📝 サマリーを保存: {summary_path}")
