"""舒心 CLI 主入口

对标 Hermes 的 cli.py，提供交互式命令行界面。
支持流式输出、彩色显示、斜杠命令。
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Optional

# 确保 shuxin 包在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shuxin.core.agent import Agent
from shuxin.core.config import Config

logger = logging.getLogger("shuxin.cli")


def setup_logging(debug: bool = False) -> None:
    """配置日志"""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner() -> None:
    """打印启动横幅"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        banner = Text()
        banner.append("╔══════════════════════════════════════╗\n", style="cyan")
        banner.append("║       舒心 (ShuXin) v0.1.0          ║\n", style="cyan bold")
        banner.append("║    陪伴型 AI 智能体框架              ║\n", style="cyan")
        banner.append("╚══════════════════════════════════════╝\n", style="cyan")

        console.print(Panel(banner, border_style="cyan"))
        console.print("输入 /help 查看命令，输入 exit 或 quit 退出\n", style="dim")
    except ImportError:
        print("=" * 50)
        print("  舒心 (ShuXin) v0.1.0 — 陪伴型 AI 智能体")
        print("=" * 50)
        print("输入 /help 查看命令，输入 exit 或 quit 退出\n")


def print_message(role: str, content: str) -> None:
    """打印格式化的消息"""
    try:
        from rich.markdown import Markdown
        from rich.console import Console

        console = Console()
        if role == "user":
            console.print(f"\n[bold green]👤 你:[/bold green]")
            console.print(f"{content}")
        elif role == "assistant":
            console.print(f"\n[bold cyan]🦊 舒心:[/bold cyan]")
            console.print(Markdown(content))
        elif role == "system":
            console.print(f"\n[bold yellow]⚙️ {content}[/bold yellow]")
        elif role == "error":
            console.print(f"\n[bold red]❌ {content}[/bold red]")
    except ImportError:
        prefix = {"user": "👤 你", "assistant": "🦊 舒心", "system": "⚙️", "error": "❌"}.get(role, "")
        print(f"\n{prefix}: {content}")


def run_interactive(agent: Agent) -> None:
    """运行交互式对话循环"""
    print_banner()
    print_message("system", "舒心已上线，随时可以开始聊天 💫")

    try:
        while True:
            # 获取用户输入
            try:
                from prompt_toolkit import PromptSession
                from prompt_toolkit.history import FileHistory
                from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

                history_path = os.path.join(
                    agent.config.shuxin_home, ".cli_history"
                )
                session = PromptSession(
                    history=FileHistory(history_path),
                    auto_suggest=AutoSuggestFromHistory(),
                )
                user_input = session.prompt("\n💬 ")
            except ImportError:
                user_input = input("\n💬 ")

            # 检查退出
            if user_input.lower() in ("exit", "quit", "bye"):
                print_message("system", "舒心轻轻挥手，目送你离开……下次见 💫")
                break

            if not user_input.strip():
                continue

            # 处理命令
            if user_input.startswith("/"):
                result = agent.handle_command(user_input)
                if result:
                    print_message("system", result)
                continue

            # 正常对话
            try:
                response = agent.chat(user_input)
                print_message("assistant", response)
            except KeyboardInterrupt:
                print_message("system", "\n（舒心歪了歪头）嗯？")
                continue
            except Exception as e:
                logger.error(f"对话出错: {e}", exc_info=True)
                print_message("error", f"出错了: {e}")

    except KeyboardInterrupt:
        print_message("system", "\n\n舒心轻轻挥手，目送你离开……下次见 💫")
    except EOFError:
        print_message("system", "\n\n舒心轻轻挥手，目送你离开……下次见 💫")


def cli_entry() -> None:
    """CLI 入口点（由 pyproject.toml 的 scripts 注册）"""
    import argparse

    parser = argparse.ArgumentParser(
        description="舒心 (ShuXin) — 陪伴型 AI 智能体框架"
    )
    parser.add_argument(
        "--config", "-c",
        help="配置文件路径",
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="启用调试日志",
    )
    parser.add_argument(
        "--model", "-m",
        help="LLM 模型名称",
    )
    parser.add_argument(
        "--provider", "-p",
        help="LLM 提供者 (openai, anthropic)",
    )
    parser.add_argument(
        "--one-shot", "-o",
        help="单次对话模式: shuxin -o '你好'",
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="显示版本信息",
    )

    args = parser.parse_args()

    if args.version:
        print("舒心 (ShuXin) v0.1.0")
        return

    # 配置日志
    setup_logging(args.debug)

    # 加载配置
    config = Config.load(args.config)

    # 命令行覆盖
    if args.model:
        config.llm.model = args.model
    if args.provider:
        config.llm.provider = args.provider

    # 初始化智能体
    agent = Agent(config)
    try:
        agent.initialize()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        print("提示: 请确保已设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    # 单次对话模式
    if args.one_shot:
        response = agent.chat(args.one_shot)
        print(response)
        return

    # 交互模式
    run_interactive(agent)


if __name__ == "__main__":
    cli_entry()
