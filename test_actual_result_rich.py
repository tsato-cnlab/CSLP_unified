#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""実際のシミュレーション結果を使ったコスト計算テスト（Rich版）

Richライブラリを使用して視覚的に見やすい出力を提供
"""

import pickle
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree
from rich import box
from rich.text import Text

from src.util.cost_calculator import (
    calc_initial_costs,
    calc_running_costs,
    calc_diff_trnsprt_costs,
    evaluation_total_costs,
    calculate_95percentile_wait_time,
    YEAR,
    DISCOUNT_RATE,
    CHARGER_COST,
    SUBSTATION_COST_PER_KW,
    INSTALLATION_COST,
    MAINTENANCE_COST_PER_YEAR,
    CONTRACT_COST_PER_KW_MONTH,
    USAGE_COST_PER_KWH,
    CHARGING_PRICE_PER_KWH,
    TIME_VALUE_OF_MONEY,
    BASELINE_TRIP_TIME,
)

console = Console()


def test_actual_simulation_result(result_file: str):
    """実際のシミュレーション結果でコスト計算をテスト"""

    result_path = Path(result_file)

    if not result_path.exists():
        console.print(f"[red]❌ ファイルが見つかりません: {result_file}[/red]")
        return

    # ヘッダー
    console.print()
    console.rule("[bold cyan]コスト計算検証ツール[/bold cyan]", style="cyan")
    console.print()

    # ファイル情報パネル
    file_info = f"""[cyan]📁 ファイル:[/cyan] {result_file}
[cyan]📏 サイズ:[/cyan] {result_path.stat().st_size / 1024:.1f} KB
[cyan]📅 最終更新:[/cyan] {Path(result_file).stat().st_mtime}"""

    console.print(Panel(file_info, title="[bold]ファイル情報[/bold]", border_style="cyan"))

    # pickleファイルを読み込み
    console.print()
    with console.status("[bold green]データ読み込み中...[/bold green]"):
        try:
            with open(result_file, 'rb') as f:
                emates_result = pickle.load(f)
            console.print("[green]✅ pickleファイル読み込み成功[/green]")
        except Exception as e:
            console.print(f"[red]❌ pickleファイル読み込みエラー: {e}[/red]")
            return

    # データ構造確認
    console.print()
    console.rule("[bold yellow]データ構造確認[/bold yellow]", style="yellow")
    console.print()

    # CS設定
    try:
        cs_config = emates_result.cs_config

        # CSテーブル
        cs_table = Table(title="充電ステーション設定", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        cs_table.add_column("CS ID", style="cyan", justify="center")
        cs_table.add_column("ポート数", style="green", justify="right")
        cs_table.add_column("容量 (kW)", style="yellow", justify="right")
        cs_table.add_column("最大出力 (kW)", style="red", justify="right")

        active_cs = [(csid, port, cap)
                     for csid, port, cap in zip(
                         cs_config.get('csids', []),
                         cs_config.get('ports', []),
                         cs_config.get('cap_kw', [])
                     ) if port > 0]

        total_ports = 0
        total_capacity = 0
        for csid, port, cap in active_cs:
            cs_table.add_row(
                f"#{csid}",
                f"{port}",
                f"{cap}",
                f"[bold]{port*cap}[/bold]"
            )
            total_ports += port
            total_capacity += cap * port

        cs_table.add_row("", "", "", "", style="dim")
        cs_table.add_row(
            "[bold]合計[/bold]",
            f"[bold]{total_ports}[/bold]",
            "-",
            f"[bold red]{total_capacity}[/bold red]"
        )

        console.print(cs_table)

    except Exception as e:
        console.print(f"[red]⚠️ CS設定の読み込みエラー: {e}[/red]")

    # 時系列データ
    try:
        timeseries_kw = emates_result.time_series_kw

        console.print()
        console.print(Panel(
            f"[cyan]タイムステップ数:[/cyan] {len(timeseries_kw):,}\n"
            f"[cyan]CS数:[/cyan] {timeseries_kw.shape[1]}",
            title="[bold]時系列データ[/bold]",
            border_style="blue"
        ))

        # 統計テーブル
        stats_table = Table(title="充電量統計", box=box.SIMPLE, show_header=True, header_style="bold blue")
        stats_table.add_column("CS", style="cyan")
        stats_table.add_column("合計 (kWh/日)", style="green", justify="right")
        stats_table.add_column("平均 (kW)", style="yellow", justify="right")
        stats_table.add_column("最大 (kW)", style="red", justify="right")

        for col_idx, col_name in enumerate(timeseries_kw.columns):
            daily_kwh = timeseries_kw[col_name].sum() / 60
            avg_kw = timeseries_kw[col_name].mean()
            max_kw = timeseries_kw[col_name].max()

            stats_table.add_row(
                f"CS{col_idx}",
                f"{daily_kwh:,.0f}",
                f"{avg_kw:.1f}",
                f"{max_kw:.1f}"
            )

        console.print()
        console.print(stats_table)

    except Exception as e:
        console.print(f"[red]⚠️ 時系列データの読み込みエラー: {e}[/red]")

    # 車両トリップデータ
    try:
        vehicle_trip = emates_result.vehicle_trip

        charging_vehicles = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
        completed = vehicle_trip[~vehicle_trip['EndTime'].isna()]

        console.print()
        trip_info = f"""[cyan]総車両数:[/cyan] {len(vehicle_trip):,} 台
[cyan]充電車両:[/cyan] {len(charging_vehicles):,} 台 ([yellow]{len(charging_vehicles)/len(vehicle_trip)*100:.1f}%[/yellow])
[cyan]完了車両:[/cyan] {len(completed):,} 台 ([green]{len(completed)/len(vehicle_trip)*100:.1f}%[/green])"""

        console.print(Panel(trip_info, title="[bold]🚗 車両トリップデータ[/bold]", border_style="green"))

    except Exception as e:
        console.print(f"[red]⚠️ 車両トリップデータの読み込みエラー: {e}[/red]")

    # ====== コスト計算 ======
    console.print()
    console.rule("[bold magenta]コスト計算[/bold magenta]", style="magenta")
    console.print()

    # 初期コスト
    with console.status("[bold green]初期コスト計算中...[/bold green]"):
        try:
            initial_costs = calc_initial_costs(cs_config, timeseries_kw)

            # 初期コストテーブル
            initial_table = Table(title="💰 初期コスト内訳", box=box.DOUBLE, show_header=True, header_style="bold cyan")
            initial_table.add_column("CS", style="cyan")
            initial_table.add_column("充電器", style="yellow", justify="right")
            initial_table.add_column("変電所", style="blue", justify="right")
            initial_table.add_column("設置", style="green", justify="right")
            initial_table.add_column("小計", style="bold red", justify="right")

            for csid, port, cap in active_cs:
                charger_cost = CHARGER_COST[str(int(cap))] * port
                substation_cost = SUBSTATION_COST_PER_KW * cap * port
                installation_cost = INSTALLATION_COST
                total = charger_cost + substation_cost + installation_cost

                initial_table.add_row(
                    f"#{csid}",
                    f"{charger_cost:,.0f}万円",
                    f"{substation_cost:,.0f}万円",
                    f"{installation_cost:,.0f}万円",
                    f"[bold]{total:,.0f}万円[/bold]"
                )

            initial_table.add_row("", "", "", "", "", style="dim")
            initial_table.add_row(
                "[bold]合計[/bold]",
                "",
                "",
                "",
                f"[bold red]{initial_costs:,.1f}万円[/bold red]"
            )

            console.print()
            console.print(initial_table)
            console.print(Panel(
                f"[bold cyan]初期コスト合計: [bold red]{initial_costs:,.1f}万円[/bold red] ≈ [bold green]{initial_costs/10000:.2f}億円[/bold green][/bold cyan]",
                border_style="cyan"
            ))

        except Exception as e:
            console.print(f"[red]❌ 初期コスト計算エラー: {e}[/red]")

    # 運用コスト
    console.print()
    with console.status("[bold green]運用コスト計算中...[/bold green]"):
        try:
            running_costs = calc_running_costs(cs_config, timeseries_kw)

            # 運用コストテーブル
            running_table = Table(title="📊 運用コスト内訳（年間）", box=box.DOUBLE, show_header=True, header_style="bold blue")
            running_table.add_column("CS", style="cyan")
            running_table.add_column("保守", style="yellow", justify="right")
            running_table.add_column("契約", style="blue", justify="right")
            running_table.add_column("充電量", style="green", justify="right")
            running_table.add_column("純収益", style="magenta", justify="right")
            running_table.add_column("純コスト", style="bold red", justify="right")

            cs_indices = [i for i, p in enumerate(cs_config.get('ports', [])) if p > 0]

            for cs_idx, (csid, port, cap) in enumerate(active_cs):
                max_capacity = cap * port

                if cs_idx < len(timeseries_kw.columns):
                    col_name = timeseries_kw.columns[cs_indices[cs_idx]]
                    daily_kwh = timeseries_kw[col_name].sum() / 60
                else:
                    daily_kwh = 0

                maintenance = MAINTENANCE_COST_PER_YEAR
                contract = CONTRACT_COST_PER_KW_MONTH * max_capacity * 12
                revenue = (CHARGING_PRICE_PER_KWH - USAGE_COST_PER_KWH) * daily_kwh * 365
                net_cost = maintenance + contract - revenue

                running_table.add_row(
                    f"#{csid}",
                    f"{maintenance:,.0f}万円",
                    f"{contract:,.1f}万円",
                    f"{daily_kwh:,.0f}kWh",
                    f"{revenue:,.1f}万円",
                    f"[bold]{net_cost:,.1f}万円[/bold]"
                )

            console.print()
            console.print(running_table)

            status_text = "[bold green]✅ 運用黒字[/bold green]" if running_costs < 0 else "[bold red]⚠️ 運用赤字[/bold red]"
            console.print(Panel(
                f"[bold cyan]年間運用コスト: [bold red]{running_costs:,.1f}万円[/bold red][/bold cyan]\n{status_text}",
                border_style="blue"
            ))

        except Exception as e:
            console.print(f"[red]❌ 運用コスト計算エラー: {e}[/red]")

    # ユーザーコスト
    console.print()
    with console.status("[bold green]ユーザーコスト計算中...[/bold green]"):
        try:
            diff_time, user_costs = calc_diff_trnsprt_costs(vehicle_trip)

            user_info = f"""[cyan]ベースライン旅行時間:[/cyan] {BASELINE_TRIP_TIME:,.1f} 時間
[cyan]差分旅行時間:[/cyan] {diff_time:,.1f} 時間
[cyan]時間価値:[/cyan] {TIME_VALUE_OF_MONEY*10000:.0f} 円/時

[bold cyan]年間ユーザーコスト:[/bold cyan] [bold red]{user_costs:,.1f}万円[/bold red]
[dim]1日あたり: {user_costs/365:,.1f}万円[/dim]"""

            status_text = "[bold red]⚠️ ユーザー負担増加[/bold red]" if user_costs > 0 else "[bold green]✅ ユーザー負担減少[/bold green]"

            console.print(Panel(
                user_info + f"\n\n{status_text}",
                title="[bold]👥 ユーザーコスト（年間）[/bold]",
                border_style="yellow"
            ))

        except Exception as e:
            console.print(f"[red]❌ ユーザーコスト計算エラー: {e}[/red]")

    # 統合コスト
    console.print()
    with console.status("[bold green]統合コスト計算中...[/bold green]"):
        try:
            total_cost, _ = evaluation_total_costs(result_file)

            running_discounted = sum(running_costs / ((1 + DISCOUNT_RATE) ** i)
                                    for i in range(1, YEAR + 1))
            user_discounted = sum(user_costs / ((1 + DISCOUNT_RATE) ** i)
                                 for i in range(1, YEAR + 1))

            # 総コストテーブル
            total_table = Table(title=f"💵 総コスト（{YEAR}年評価、割引率{DISCOUNT_RATE*100:.0f}%）", box=box.HEAVY, show_header=True, header_style="bold magenta")
            total_table.add_column("項目", style="cyan")
            total_table.add_column("金額", style="bold red", justify="right")
            total_table.add_column("構成比", style="yellow", justify="right")

            if total_cost != 0:
                initial_ratio = abs(initial_costs) / abs(total_cost) * 100
                running_ratio = abs(running_discounted) / abs(total_cost) * 100
                user_ratio = abs(user_discounted) / abs(total_cost) * 100
            else:
                initial_ratio = running_ratio = user_ratio = 0

            total_table.add_row("初期コスト", f"{initial_costs:,.1f}万円", f"{initial_ratio:.1f}%")
            total_table.add_row("運用コスト（割引後）", f"{running_discounted:,.1f}万円", f"{running_ratio:.1f}%")
            total_table.add_row("ユーザーコスト（割引後）", f"{user_discounted:,.1f}万円", f"{user_ratio:.1f}%")
            total_table.add_row("", "", "", style="dim")
            total_table.add_row(
                "[bold]総コスト[/bold]",
                f"[bold red]{total_cost:,.1f}万円[/bold red]",
                "100.0%"
            )

            console.print()
            console.print(total_table)
            console.print(Panel(
                f"[bold cyan]総コスト: [bold red]{total_cost:,.1f}万円[/bold red] ≈ [bold green]{total_cost/10000:.2f}億円[/bold green][/bold cyan]",
                border_style="magenta"
            ))

        except Exception as e:
            console.print(f"[red]❌ 統合コスト計算エラー: {e}[/red]")

    # 待ち時間
    console.print()
    with console.status("[bold green]待ち時間計算中...[/bold green]"):
        try:
            wait_time_95p = calculate_95percentile_wait_time(result_file)

            if wait_time_95p == float('inf'):
                wait_text = "[red]⚠️ 充電できた車両がありません[/red]"
            else:
                wait_text = f"[bold cyan]95パーセンタイル待ち時間:[/bold cyan] [bold yellow]{wait_time_95p:.1f}秒[/bold yellow] ≈ [bold green]{wait_time_95p/60:.1f}分[/bold green]"

            console.print(Panel(wait_text, title="[bold]⏱️ 待ち時間分析[/bold]", border_style="cyan"))

        except Exception as e:
            console.print(f"[red]❌ 待ち時間計算エラー: {e}[/red]")

    # サマリー
    console.print()
    console.rule("[bold green]テスト結果サマリー[/bold green]", style="green")
    console.print()

    # ツリー表示
    tree = Tree("📊 [bold cyan]コスト計算結果[/bold cyan]")
    tree.add(f"[green]✅[/green] 初期コスト: [yellow]{initial_costs:,.1f}万円[/yellow]")
    tree.add(f"[green]✅[/green] 運用コスト: [yellow]{running_costs:,.1f}万円/年[/yellow]")
    tree.add(f"[green]✅[/green] ユーザーコスト: [yellow]{user_costs:,.1f}万円/年[/yellow]")
    tree.add(f"[green]✅[/green] 統合コスト: [yellow]{total_cost:,.1f}万円[/yellow]")

    if wait_time_95p != float('inf'):
        tree.add(f"[green]✅[/green] 待ち時間: [yellow]{wait_time_95p:.1f}秒[/yellow]")

    console.print(tree)
    console.print()
    console.print(Panel("[bold green]✨ 実データでのコスト計算: 正常動作確認 ✨[/bold green]", border_style="green", style="bold"))
    console.print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result_file = sys.argv[1]
    else:
        result_file = "/srv/samba/share/output/unified_P10_P10/trial_1_combo_1_normal.pkl"

    test_actual_simulation_result(result_file)
