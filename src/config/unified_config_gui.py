"""統合最適化用のStreamlit GUI"""
import streamlit as st
from pathlib import Path
import json
from dataclasses import asdict
from unified_optimization_config import (
    UnifiedOptimizationConfig,
    ObjectiveFunction
)


def main():
    st.set_page_config(
        page_title="統合最適化設定",
        page_icon="🔥",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # ===== サイドバー: プリセット選択 =====
    with st.sidebar:
        st.header("🎯 プリセット設定")

        preset_options = {
            "カスタム": None,
            "クイックテスト (10試行)": "quick_test",
            "平常時のみ (P=0)": "normal_only",
            "故障時のみ (P=1)": "failure_only",
            "バランス型 (P=0.5)": "balanced",
            "堅牢性重視 (P=0.8)": "robust",
            "本番環境 (3000試行)": "production"
        }

        selected_preset = st.selectbox(
            "プリセットを選択",
            options=list(preset_options.keys()),
            help="よく使う設定をすぐに読み込めます"
        )

        # プリセット読み込み
        if selected_preset != "カスタム" and preset_options[selected_preset]:
            if 'config' not in st.session_state or st.button("🔄 プリセットを適用"):
                st.session_state.config = UnifiedOptimizationConfig.create_preset(
                    preset_options[selected_preset]
                )
                st.success(f"✅ {selected_preset}を読み込みました")

        # JSONから読み込み
        st.divider()
        st.subheader("📂 設定ファイル")
        uploaded_file = st.file_uploader("JSONから読み込み", type=['json'])
        if uploaded_file:
            try:
                data = json.load(uploaded_file)
                # ObjectiveFunctionの復元
                if 'objective_function' in data:
                    obj_func_data = data['objective_function']
                    data['objective_function'] = ObjectiveFunction(**obj_func_data)
                st.session_state.config = UnifiedOptimizationConfig(**data)
                st.success("✅ 設定を読み込みました")
            except Exception as e:
                st.error(f"❌ エラー: {e}")

    # 初期設定
    if 'config' not in st.session_state:
        st.session_state.config = UnifiedOptimizationConfig()

    config = st.session_state.config

    # ===== メインコンテンツ =====
    st.title("🔥 統合最適化設定 GUI")
    st.markdown("""
    平常時と故障時を統合した最適化の設定を行います。
    """)

    # 現在の目的関数を表示
    st.info(f"**目的関数**: {config.get_objective_formula()}")

    # ===== タブ構成 =====
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🎯 最適化モード",
        "🔢 目的関数",
        "📁 基本設定",
        "⚡ 並列処理",
        "🔧 詳細設定",
        "📊 プレビュー"
    ])

    # ----- Tab 1: 最適化モード -----
    with tab1:
        st.header("最適化モード選択")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📊 平常時のみ\n(P=0)", use_container_width=True, type="secondary"):
                config.failure_weight = 0.0
                config.optimization_mode = "normal"
                config.workers_per_trial = 1

        with col2:
            if st.button("🔥 故障時のみ\n(P=1)", use_container_width=True, type="secondary"):
                config.failure_weight = 1.0
                config.optimization_mode = "failure"
                config.workers_per_trial = 9

        with col3:
            if st.button("⚖️ 統合最適化\n(0<P<1)", use_container_width=True, type="primary"):
                config.failure_weight = 0.5
                config.optimization_mode = "unified"
                config.workers_per_trial = 9

        st.divider()

        # P値スライダー
        st.subheader("故障重み（P値）の設定")
        config.failure_weight = st.slider(
            "故障重み P",
            min_value=0.0,
            max_value=1.0,
            value=config.failure_weight,
            step=0.05,
            format="%.2f",
            help="0.0=平常時のみ、1.0=故障時のみ、0.5=両方を均等に考慮"
        )

        # 視覚化
        col_viz1, col_viz2 = st.columns(2)
        with col_viz1:
            st.metric("平常時の重み", f"{config.normal_weight:.2f}")
        with col_viz2:
            st.metric("故障時の重み", f"{config.failure_weight:.2f}")

        # 推奨設定の説明
        with st.expander("💡 P値の選び方ガイド"):
            st.markdown("""
            | P値 | 用途 | 説明 |
            |-----|------|------|
            | 0.0 | コスト最小化 | 平常時のコストのみを最小化 |
            | 0.2-0.3 | 軽微な堅牢性 | 故障時も少し考慮 |
            | 0.5 | バランス型 | 平常時と故障時を同等に考慮 |
            | 0.7-0.8 | 堅牢性重視 | 故障時の性能を重視 |
            | 1.0 | ロバスト設計 | 最悪ケースに対して最適化 |
            """)

    # ----- Tab 2: 目的関数 -----
    with tab2:
        st.header("目的関数の設定")

        st.markdown("""
        目的関数を選択・カスタマイズできます。
        `normal`: 平常時コスト、`failure`: 故障時コスト、`P`: 故障重み
        """)

        # 事前定義された目的関数
        predefined_funcs = ObjectiveFunction.get_predefined_functions()

        func_options = {
            "重み付き和（デフォルト）": "weighted_sum",
            "最大値（最も保守的）": "max",
            "重み付き最大値": "weighted_max",
            "幾何平均": "geometric_mean",
            "カスタム式": "custom"
        }

        selected_func = st.selectbox(
            "目的関数を選択",
            options=list(func_options.keys()),
            index=list(func_options.values()).index(config.objective_function.name)
                if config.objective_function.name in func_options.values() else 0,
            help="最適化する目的関数のタイプを選択"
        )

        func_name = func_options[selected_func]

        # 選択された関数の説明
        if func_name in predefined_funcs:
            selected_obj_func = predefined_funcs[func_name]
            st.info(f"**数式**: {selected_obj_func.formula}")
            st.write(f"**説明**: {selected_obj_func.description}")
            config.objective_function = selected_obj_func

        # カスタム式の入力
        if func_name == "custom":
            st.subheader("カスタム数式を入力")

            custom_formula = st.text_input(
                "数式（Python式）",
                value=config.objective_function.formula if config.objective_function.name == "custom"
                    else "(1-P) * normal + P * failure",
                help="使用可能: normal, failure, P, max(), min(), abs()"
            )

            config.objective_function = ObjectiveFunction(
                name="custom",
                formula=custom_formula,
                description="カスタム式"
            )

            # カスタム式のテスト
            st.subheader("式のテスト")
            col_test1, col_test2, col_test3 = st.columns(3)

            with col_test1:
                test_normal = st.number_input("テスト用平常時コスト", value=100.0)
            with col_test2:
                test_failure = st.number_input("テスト用故障時コスト", value=150.0)
            with col_test3:
                test_p = st.number_input("テスト用P値", value=0.5, min_value=0.0, max_value=1.0)

            if st.button("式をテスト"):
                try:
                    result = config.objective_function.calculate(test_normal, test_failure, test_p)
                    if result == float('inf'):
                        st.error("❌ 式の評価に失敗しました")
                    else:
                        st.success(f"✅ 結果: {result:.2f}")
                except Exception as e:
                    st.error(f"❌ エラー: {e}")

        # 目的関数のプレビュー
        st.divider()
        st.subheader("目的関数のプレビュー")

        # サンプルデータでグラフ表示
        import pandas as pd
        import numpy as np

        normal_costs = np.linspace(50, 200, 10)
        failure_costs = np.linspace(100, 250, 10)

        preview_data = []
        for nc in normal_costs:
            for fc in failure_costs:
                obj_val = config.calculate_objective(nc, fc)
                preview_data.append({
                    '平常時コスト': nc,
                    '故障時コスト': fc,
                    '目的関数値': obj_val
                })

        df_preview = pd.DataFrame(preview_data)

        # 3Dプロットの代わりにヒートマップ
        import plotly.express as px
        pivot_df = df_preview.pivot(
            index='故障時コスト',
            columns='平常時コスト',
            values='目的関数値'
        )

        fig = px.imshow(
            pivot_df,
            labels=dict(x="平常時コスト", y="故障時コスト", color="目的関数値"),
            title=f"目的関数のヒートマップ (P={config.failure_weight:.2f})",
            color_continuous_scale="Viridis"
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("💡 目的関数の選び方"):
            st.markdown("""
            - **重み付き和**: 標準的な方法。平常時と故障時のバランスを取る
            - **最大値**: 最も保守的。ワーストケースを最小化
            - **重み付き最大値**: 保守的だが重みを考慮
            - **幾何平均**: 両方のコストが極端に大きくなるのを防ぐ
            - **カスタム**: 独自の評価基準を実装可能
            """)

    # ----- Tab 3: 基本設定 -----
    with tab3:
        st.header("基本設定")

        col_basic1, col_basic2 = st.columns(2)

        with col_basic1:
            config.experiment_name = st.text_input(
                "実験名",
                value=config.experiment_name,
                help="ディレクトリ名に含まれます"
            )

            config.save_dir_base = st.text_input(
                "保存先ベースディレクトリ",
                value=config.save_dir_base,
                help="この下にタイムスタンプ付きディレクトリが作成されます"
            )

            # 実際の保存先プレビュー
            st.info(f"📁 **実際の保存先**: `{config.save_dir}`")

        with col_basic2:
            config.t_hour = st.number_input(
                "シミュレーション時間（時）",
                min_value=1,
                max_value=48,
                value=config.t_hour,
                help="通常は26時間"
            )

            config.total_trials = st.number_input(
                "総トライアル数",
                min_value=1,
                max_value=10000,
                value=config.total_trials,
                help="最適化の総試行回数"
            )

    # ----- Tab 4: 並列処理 -----
    with tab4:
        st.header("並列処理設定")

        col_para1, col_para2 = st.columns(2)

        with col_para1:
            config.outer_parallel = st.slider(
                "同時実行トライアル数 (outer_parallel)",
                min_value=1,
                max_value=16,
                value=config.outer_parallel,
                help="同時に評価するトライアルの数"
            )

            config.batch_size = st.slider(
                "バッチサイズ",
                min_value=1,
                max_value=32,
                value=config.batch_size,
                help="（互換性のため保持、実際はouter_parallelを使用）"
            )

        with col_para2:
            # Worker数の表示
            total_workers = config.get_total_workers()
            st.metric(
                "必要なWorker数",
                total_workers,
                help=f"{config.outer_parallel}トライアル × {config.workers_per_trial}Worker"
            )

            # 推定実行時間
            time_per_trial = st.number_input(
                "1トライアルあたりの時間（分）",
                min_value=1.0,
                max_value=60.0,
                value=5.0,
                step=0.5,
                help="経験的な実行時間を入力"
            )

            estimated = config.get_estimated_time(time_per_trial)
            st.metric(
                "推定実行時間",
                f"{estimated['hours']:.1f} 時間",
                help=f"{estimated['minutes']:.0f}分 ≈ {estimated['days']:.2f}日"
            )

    # ----- Tab 5: 詳細設定 -----
    with tab5:
        st.header("詳細設定")

        col_adv1, col_adv2 = st.columns(2)

        with col_adv1:
            st.subheader("収束判定")
            config.convergence_patience = st.number_input(
                "収束判定回数",
                min_value=10,
                max_value=500,
                value=config.convergence_patience,
                help="連続してこの回数改善が小さい場合に収束と判定"
            )

            config.convergence_threshold = st.number_input(
                "収束閾値",
                min_value=0.0001,
                max_value=0.1,
                value=config.convergence_threshold,
                format="%.4f",
                help="改善率がこの値未満で収束"
            )

            config.timeout = st.number_input(
                "タイムアウト（秒）",
                min_value=3600,
                max_value=86400 * 7,
                value=config.timeout,
                help="最大実行時間"
            )

        with col_adv2:
            st.subheader("Optuna設定")
            config.n_startup_trials = st.number_input(
                "ランダム探索期間",
                min_value=10,
                max_value=200,
                value=config.n_startup_trials,
                help="最初のランダム探索トライアル数"
            )

            st.subheader("故障シナリオ")
            config.failure_flag = st.checkbox(
                "故障シナリオを有効化",
                value=config.failure_flag
            )

            if config.failure_flag:
                failure_time_range = st.slider(
                    "故障発生時間範囲（時）",
                    min_value=0,
                    max_value=config.t_hour,
                    value=(0, config.t_hour),
                    help="この範囲で故障が発生する可能性がある"
                )
                config.failure_time = list(range(
                    failure_time_range[0],
                    failure_time_range[1] + 1
                ))

    # ----- Tab 6: プレビュー -----
    with tab6:
        st.header("設定プレビュー")

        # 検証
        errors = config.validate()
        if errors:
            st.error("❌ 設定エラー:")
            for error in errors:
                st.write(f"- {error}")
        else:
            st.success("✅ 設定は正常です")

        # サマリー表示
        col_sum1, col_sum2, col_sum3 = st.columns(3)

        with col_sum1:
            st.subheader("最適化設定")
            st.write(f"- モード: {config.optimization_mode}")
            st.write(f"- 故障重み: {config.failure_weight:.2f}")
            st.write(f"- 目的関数: {config.objective_function.name}")
            st.write(f"- トライアル数: {config.total_trials}")
            st.write(f"- 収束判定: {config.convergence_patience}回")

        with col_sum2:
            st.subheader("並列処理")
            st.write(f"- 同時トライアル: {config.outer_parallel}")
            st.write(f"- Worker/トライアル: {config.workers_per_trial}")
            st.write(f"- 総Worker数: {config.get_total_workers()}")

        with col_sum3:
            st.subheader("実行環境")
            st.write(f"- 保存先: `{config.experiment_name}`")
            st.write(f"- シミュレーション時間: {config.t_hour}時間")
            st.write(f"- タイムアウト: {config.timeout/3600:.1f}時間")

        # JSON表示
        with st.expander("📄 JSON設定（デバッグ用）"):
            st.json(asdict(config))

    # ===== 保存ボタン =====
    st.divider()
    col_save1, col_save2, col_save3 = st.columns([2, 1, 1])

    with col_save1:
        config_filename = st.text_input(
            "設定ファイル名",
            value="unified_config.json",
            help="保存する設定ファイル名"
        )

    with col_save2:
        if st.button("💾 設定を保存", type="primary", use_container_width=True):
            try:
                config.to_json(Path(config_filename))
                st.success(f"✅ `{config_filename}`に保存しました")
            except Exception as e:
                st.error(f"❌ 保存エラー: {e}")

    with col_save3:
        if st.button("📋 実行コマンドを表示", use_container_width=True):
            st.code(f"python cs_optim_unified.py {config_filename}", language="bash")

    # ===== 使用方法 =====
    with st.expander("📖 使用方法"):
        st.markdown(f"""
        ### GUI起動方法
        ```bash
        cd {Path.cwd()}
        source .venv/bin/activate
        streamlit run src/config/unified_config_gui.py
        ```

        ### 設定ファイルの使用方法
        ```python
        from src.config.unified_optimization_config import UnifiedOptimizationConfig

        # 設定読み込み
        config = UnifiedOptimizationConfig.from_json(Path("unified_config.json"))

        # 目的関数の計算
        unified_cost = config.calculate_objective(
            normal_cost=100.0,
            failure_cost=150.0
        )
        ```

        ### 最適化実行
        ```bash
        # デフォルト設定で実行
        python cs_optim_unified.py

        # GUI設定を使用
        python cs_optim_unified.py unified_config.json
        ```

        ### 目的関数のカスタマイズ例
        ```python
        # 例1: ペナルティ付き重み付き和
        "(1-P) * normal + P * failure + 0.1 * abs(normal - failure)"

        # 例2: 条件付き評価
        "normal if failure < 200 else failure"

        # 例3: 非線形重み
        "(1-P**2) * normal + P**2 * failure"
        ```
        """)


if __name__ == "__main__":
    main()
