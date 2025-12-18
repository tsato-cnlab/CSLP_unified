"""Streamlitベースの最適化設定GUI"""
import streamlit as st
from pathlib import Path
from optimization_config import OptimizationConfig, FailureScenarioConfig


def main():
    st.set_page_config(page_title="eMATES 最適化設定", page_icon="⚡", layout="wide")

    st.title("⚡ eMATES 最適化設定")
    st.markdown("パラメータをGUIで設定し、JSONファイルに保存できます。")

    # タブで設定を分類
    tab1, tab2, tab3 = st.tabs(["基本設定", "最適化設定", "故障シナリオ設定"])

    with tab1:
        st.header("基本設定")
        save_dir = st.text_input(
            "保存ディレクトリ",
            value="/srv/samba/share/output",
            help="最適化結果を保存するディレクトリパス"
        )
        t_hour = st.number_input(
            "シミュレーション時間（時）",
            min_value=1,
            max_value=48,
            value=26,
            help="シミュレーション時間を時間単位で指定"
        )

    with tab2:
        st.header("最適化設定")
        col1, col2 = st.columns(2)

        with col1:
            batch_size = st.slider(
                "バッチサイズ",
                min_value=1,
                max_value=16,
                value=8,
                help="並列実行するトライアル数"
            )
            total_trials = st.number_input(
                "総トライアル数",
                min_value=1,
                value=1000,
                help="最適化の総試行回数"
            )

        with col2:
            timeout = st.number_input(
                "タイムアウト（秒）",
                min_value=3600,
                value=86400,
                help="24時間 = 86400秒"
            )
            convergence_patience = st.number_input(
                "収束判定回数",
                min_value=10,
                value=100,
                help="連続してこの回数改善が小さい場合に収束と判定"
            )
            convergence_threshold = st.number_input(
                "収束閾値",
                min_value=0.001,
                max_value=0.1,
                value=0.01,
                format="%.3f",
                help="改善率がこの値未満の場合に収束と判定"
            )

    with tab3:
        st.header("故障シナリオ設定")

        failure_flag = st.checkbox(
            "故障シナリオを有効化",
            value=True,
            help="故障時最適化・確率的最適化で使用"
        )

        if failure_flag:
            col3, col4 = st.columns(2)

            with col3:
                failure_probability = st.slider(
                    "故障確率",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.2,
                    format="%.2f",
                    help="全CSのうち一か所が故障する確率"
                )

            with col4:
                charger_failure_rate = st.slider(
                    "充電器故障率",
                    min_value=0.0,
                    max_value=0.1,
                    value=0.02,
                    format="%.3f",
                    help="各充電器の故障率"
                )

            failure_time_range = st.slider(
                "故障発生時間範囲（時）",
                min_value=0,
                max_value=t_hour,
                value=(0, t_hour),
                help="故障が発生する可能性のある時間範囲"
            )
            failure_time = list(range(failure_time_range[0], failure_time_range[1] + 1))
        else:
            failure_probability = 0.0
            charger_failure_rate = 0.0
            failure_time = []

    # 設定保存
    st.divider()
    col_save1, col_save2 = st.columns([3, 1])

    with col_save1:
        config_filename = st.text_input(
            "設定ファイル名",
            value="config.json",
            help="保存する設定ファイルの名前"
        )

    with col_save2:
        if st.button("💾 設定を保存", type="primary", use_container_width=True):
            try:
                # 最適化設定を保存
                config = OptimizationConfig(
                    save_dir=save_dir,
                    t_hour=t_hour,
                    batch_size=batch_size,
                    total_trials=total_trials,
                    timeout=timeout,
                    convergence_patience=convergence_patience,
                    convergence_threshold=convergence_threshold
                )
                config.to_json(Path(config_filename))

                # 故障シナリオ設定を保存
                failure_config = FailureScenarioConfig(
                    failure_flag=failure_flag,
                    failure_time=failure_time,
                    failure_probability=failure_probability,
                    charger_failure_rate=charger_failure_rate
                )
                failure_config.to_json(Path(f"failure_{config_filename}"))

                st.success(f"✅ 設定を保存しました！\n- {config_filename}\n- failure_{config_filename}")

                # 設定内容のプレビュー
                with st.expander("保存した設定を確認"):
                    st.json(config.__dict__)
                    if failure_flag:
                        st.json(failure_config.__dict__)

            except Exception as e:
                st.error(f"❌ エラー: {e}")

    # 使用方法の説明
    with st.expander("📖 使用方法"):
        st.markdown("""
        ### GUI起動方法
        ```bash
        uv run streamlit run src/config/config_gui.py
        ```

        ### 設定ファイルの読み込み方法
        ```python
        from src.config.optimization_config import OptimizationConfig

        config = OptimizationConfig.from_json(Path("config.json"))
        print(config.batch_size)  # 8
        ```

        ### 3つの最適化モード
        - **平常時最適化** (`cs_optimization_Optuna copy.py`): 故障なしの通常最適化
        - **故障時最適化** (`cs_optim_fail.py`): ロバスト設計、最悪ケース
        - **確率的最適化** (`cs_optim_prob.py`): 故障確率を考慮した期待値ベース
        """)


if __name__ == "__main__":
    main()
