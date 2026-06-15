"""初心 CLI 主入口

对标 Hermes 的 cli.py，提供交互式命令行界面。
支持流式输出、彩色显示、斜杠命令、历史记录。

使用方式：
    shuxin                      # 交互模式（首次会引导选择模型和 API 密钥）
    shuxin -o "你好"            # 单次对话模式
    shuxin --debug              # 调试模式
    shuxin --version            # 版本信息
    shuxin -p openai -m gpt-4o  # 指定提供者和模型
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Optional

# 确保 shuxin 包在路径中（src layout: shuxin/src/shuxin/cli/main.py → shuxin/src）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 设置标准输出编码为 UTF-8，避免 Windows GBK 终端下 emoji 报错
if sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from shuxin.core.agent import Agent
from shuxin.core.config import Config, PROVIDER_MODELS, get_provider_model_ids

logger = logging.getLogger("shuxin.cli")

# 版本信息
VERSION = "0.2.0"
APP_NAME = "初心 (ChuXin)"


def setup_logging(debug: bool = False) -> None:
    """配置日志系统。

    Args:
        debug: 是否启用调试级别日志。如果为 False，默认使用 WARNING 级别。
    """
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner() -> None:
    """打印启动横幅。

    优先使用 rich 库渲染彩色面板，如果 rich 未安装则使用纯文本。
    """
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        banner = Text()
        banner.append("╔══════════════════════════════════════╗\n", style="cyan")
        banner.append(f"║       {APP_NAME} v{VERSION}          ║\n", style="cyan bold")
        banner.append("║    陪伴型 AI 智能体框架              ║\n", style="cyan")
        banner.append("╚══════════════════════════════════════╝\n", style="cyan")

        console.print(Panel(banner, border_style="cyan"))
        console.print("输入 /help 查看命令，输入 exit 或 quit 退出\n", style="dim")
    except (ImportError, UnicodeEncodeError):
        print("=" * 50)
        print(f"  {APP_NAME} v{VERSION} — 陪伴型 AI 智能体")
        print("=" * 50)
        print("输入 /help 查看命令，输入 exit 或 quit 退出\n")


def _get_role_prefix(role: str) -> str:
    """根据角色和终端编码获取合适的前缀文本。

    Args:
        role: 消息角色 (user, assistant, system, error)。

    Returns:
        格式化的前缀字符串。
    """
    if _supports_emoji():
        prefix_map = {
            "user": "👤 你",
            "assistant": "🦊 初心",
            "system": "⚙️",
            "error": "❌",
        }
    else:
        prefix_map = {
            "user": "[你]",
            "assistant": "[初心]",
            "system": "[系统]",
            "error": "[错误]",
        }
    return prefix_map.get(role, "")


def print_message(role: str, content: str) -> None:
    """打印格式化的消息。

    根据角色使用不同的颜色和图标：
    - user: 绿色
    - assistant: 青色 + Markdown 渲染
    - system: 黄色
    - error: 红色

    Args:
        role: 消息角色 (user, assistant, system, error)。
        content: 消息内容。
    """
    prefix = _get_role_prefix(role)
    try:
        from rich.markdown import Markdown
        from rich.console import Console

        console = Console()
        if role == "user":
            console.print(f"\n[bold green]{prefix}:[/bold green]")
            console.print(f"{content}")
        elif role == "assistant":
            console.print(f"\n[bold cyan]{prefix}:[/bold cyan]")
            console.print(Markdown(content))
        elif role == "system":
            console.print(f"\n[bold yellow]{prefix}: {content}[/bold yellow]")
        elif role == "error":
            console.print(f"\n[bold red]{prefix}: {content}[/bold red]")
    except (ImportError, UnicodeEncodeError):
        print(f"\n{prefix}: {content}")


def run_interactive(agent: Agent) -> None:
    """运行交互式对话循环。

    使用 prompt_toolkit 提供历史记录和自动建议功能。
    如果 prompt_toolkit 未安装，回退到标准 input()。

    Args:
        agent: 已初始化的 Agent 实例。
    """
    print_banner()

    # 显示当前使用的模型信息
    provider_label = PROVIDER_MODELS.get(agent.config.llm.provider, {}).get(
        "label", agent.config.llm.provider
    )
    print_message(
        "system",
        f"初心已上线 🦊\n"
        f"  提供者: {provider_label}\n"
        f"  模型: {agent.config.llm.model}\n"
        f"  输入 /help 查看命令",
    )

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
                print_message("system", "初心轻轻挥手，目送你离开……下次见 💫")
                break

            if not user_input.strip():
                continue

            # 处理命令
            if user_input.startswith("/"):
                # 内置命令：重置 API 密钥
                if user_input.strip() == "/reset-key":
                    _handle_reset_key(agent)
                    continue

                # 内置命令：切换模型
                if user_input.strip() == "/switch-model":
                    _handle_switch_model(agent)
                    continue

                try:
                    result = agent.handle_command(user_input)
                    if result:
                        print_message("system", result)
                except Exception as e:
                    logger.error("命令处理失败: %s", e, exc_info=True)
                    print_message("error", f"命令执行出错: {e}")
                continue

            # 正常对话
            try:
                response = agent.chat(user_input)
                print_message("assistant", response)
            except KeyboardInterrupt:
                print_message("system", "\n（初心歪了歪头）嗯？")
                continue
            except RuntimeError as e:
                logger.error("对话出错: %s", e, exc_info=True)
                error_msg = str(e)
                print_message("error", error_msg)
                # API 密钥错误时提示重新设置
                if "API 密钥无效" in error_msg or "401" in error_msg:
                    print_message(
                        "system",
                        "提示: 输入 /reset-key 可重新设置 API 密钥",
                    )
            except Exception as e:
                logger.error("对话出错: %s", e, exc_info=True)
                print_message("error", f"出错了: {e}")

    except KeyboardInterrupt:
        print_message("system", "\n\n初心轻轻挥手，目送你离开……下次见 💫")
    except EOFError:
        print_message("system", "\n\n初心轻轻挥手，目送你离开……下次见 💫")


def _supports_emoji() -> bool:
    """检测当前终端是否支持 emoji 显示。

    Returns:
        如果终端编码为 UTF-8 则返回 True，否则返回 False。
    """
    encoding = sys.stdout.encoding or ""
    return "utf" in encoding.lower() or "utf8" in encoding.lower()


# =============================================================================
# 交互式设置流程
# =============================================================================


def _prompt_provider_selection() -> str:
    """交互式选择 LLM 提供者。

    显示所有可用提供者列表，让用户选择。

    Returns:
        选中的提供者名称（如 "openai", "anthropic", "deepseek"）。
    """
    emoji = _supports_emoji()

    print(f"\n{'🌐 ' if emoji else ''}请选择 LLM 提供者（模型服务商）:")
    print(f"{'   '}你可以使用上下方向键或输入编号选择。\n")

    provider_keys = list(PROVIDER_MODELS.keys())
    # 把 openai-compatible 放到最后
    if "openai-compatible" in provider_keys:
        provider_keys.remove("openai-compatible")
        provider_keys.append("openai-compatible")

    for i, key in enumerate(provider_keys, 1):
        info = PROVIDER_MODELS[key]
        print(f"  {i}. {info['label']}")
        print(f"     {info['description']}")
        print()

    attempts = 0
    max_attempts = 5
    while attempts < max_attempts:
        try:
            choice = input(f"{'🔢 ' if emoji else ''}请输入编号 (1-{len(provider_keys)}): ").strip()
            if not choice:
                attempts += 1
                if attempts < max_attempts:
                    print(f"输入不能为空，请重新输入 (1-{len(provider_keys)})。")
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(provider_keys):
                selected = provider_keys[idx]
                print(f"{'✅ ' if emoji else ''}已选择: {PROVIDER_MODELS[selected]['label']}")
                return selected
            print(f"请输入 1-{len(provider_keys)} 之间的数字。")
            attempts += 1
        except (ValueError, EOFError, KeyboardInterrupt):
            attempts += 1
            if attempts < max_attempts:
                print(f"请输入 1-{len(provider_keys)} 之间的数字。")

    # 超过最大尝试次数，使用默认值
    print(f"\n{'⚠️ ' if emoji else ''}未选择，默认使用 OpenAI")
    return "openai"


def _prompt_model_selection(provider: str) -> str:
    """交互式选择模型。

    Args:
        provider: 已选定的提供者名称。

    Returns:
        选中的模型 ID（如 "gpt-4o", "claude-3-5-sonnet-20241022"）。
    """
    emoji = _supports_emoji()
    provider_info = PROVIDER_MODELS.get(provider)

    if not provider_info:
        return "gpt-4o"

    models = provider_info.get("models", [])

    print(f"\n{'🤖 ' if emoji else ''}请选择 {provider_info['label']} 的模型:")

    for i, (model_id, desc) in enumerate(models, 1):
        print(f"  {i}. {model_id}")
        print(f"     {desc}")
        print()

    # 如果是 openai-compatible，允许自定义输入
    if provider == "openai-compatible":
        print(f"  {len(models) + 1}. 自定义模型名称")
        print()

    attempts = 0
    max_attempts = 5
    while attempts < max_attempts:
        try:
            choice = input(f"{'🔢 ' if emoji else ''}请输入编号 (1-{len(models)}): ").strip()
            if not choice:
                attempts += 1
                if attempts < max_attempts:
                    print(f"输入不能为空，请重新输入 (1-{len(models)})。")
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx][0]
                print(f"{'✅ ' if emoji else ''}已选择: {selected}")
                return selected
            if provider == "openai-compatible" and idx == len(models):
                custom = input(f"{'✏️ ' if emoji else ''}请输入模型名称: ").strip()
                if custom:
                    print(f"{'✅ ' if emoji else ''}已选择: {custom}")
                    return custom
            print(f"请输入 1-{len(models)} 之间的数字。")
            attempts += 1
        except (ValueError, EOFError, KeyboardInterrupt):
            attempts += 1
            if attempts < max_attempts:
                print(f"请输入 1-{len(models)} 之间的数字。")

    # 超过最大尝试次数，使用默认模型
    default_model = models[0][0] if models else "gpt-4o"
    print(f"\n{'⚠️ ' if emoji else ''}未选择，默认使用 {default_model}")
    return default_model


def _prompt_base_url(provider: str) -> str:
    """交互式输入自定义 API 地址。

    Args:
        provider: 提供者名称。

    Returns:
        用户输入的 base_url（可能为空字符串）。
    """
    emoji = _supports_emoji()
    provider_info = PROVIDER_MODELS.get(provider, {})
    env_base_url = provider_info.get("env_base_url", "")

    print(f"\n{'🔗 ' if emoji else ''}API 地址设置")
    print(f"   环境变量: {env_base_url}")
    print(f"   留空则使用默认地址。")

    try:
        url = input(f"{'🔗 ' if emoji else ''}请输入 API 地址（留空使用默认）: ").strip()
        return url
    except (EOFError, KeyboardInterrupt):
        return ""


def _prompt_for_api_key(provider: str) -> str:
    """交互式提示用户输入 API 密钥。

    Args:
        provider: 提供者名称，用于显示对应的环境变量名。

    Returns:
        用户输入的 API 密钥字符串（可能为空）。
    """
    emoji = _supports_emoji()
    provider_info = PROVIDER_MODELS.get(provider, {})
    env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")

    prompt_text = (
        f"{'🔑 ' if emoji else ''}"
        f"请输入 {provider_info.get('label', provider)} API 密钥"
        f"（或设置 {env_api_key} 环境变量跳过此步）: "
    )
    try:
        from getpass import getpass
        api_key = getpass(prompt_text)
    except (ImportError, EOFError):
        api_key = input(prompt_text)
    return api_key.strip()


def _ensure_setup(config: Config) -> None:
    """确保配置完整：提供者、模型、API 密钥。

    首次使用时引导用户完成：
    1. 选择 LLM 提供者
    2. 选择模型
    3. 输入 API 密钥（可选 base_url）

    如果配置中已有完整信息（provider, model, api_key），则跳过引导。

    Args:
        config: 配置实例，可能被修改。
    """
    emoji = _supports_emoji()

    # 检查是否已有完整配置
    has_provider = bool(config.llm.provider and config.llm.provider != "openai")
    has_model = bool(config.llm.model and config.llm.model != "gpt-4o")
    has_key = bool(config.llm.api_key or os.environ.get("OPENAI_API_KEY"))

    # 如果已有完整配置（非默认值），跳过引导
    if has_provider and has_model and has_key:
        return

    # 如果只有默认值，进行完整引导
    is_first_run = not (has_provider or has_model or has_key)

    if is_first_run:
        print(f"\n{'🎉 ' if emoji else ''}欢迎使用初心！首次运行需要完成以下设置：")
        print(f"   1. 选择 LLM 提供者（模型服务商）")
        print(f"   2. 选择模型")
        print(f"   3. 输入 API 密钥\n")

    # 1. 选择提供者（如果尚未设置或为默认值）
    if not has_provider:
        provider = _prompt_provider_selection()
        config.llm.provider = provider
    else:
        provider = config.llm.provider

    # 2. 选择模型（如果尚未设置或为默认值）
    if not has_model:
        model = _prompt_model_selection(provider)
        config.llm.model = model

    # 2.5 如果是 openai-compatible 或 deepseek，询问 base_url
    provider_info = PROVIDER_MODELS.get(provider, {})
    if provider == "openai-compatible" and not config.llm.base_url:
        base_url = _prompt_base_url(provider)
        if base_url:
            config.llm.base_url = base_url
    elif provider == "deepseek" and not config.llm.base_url:
        # DeepSeek 默认 base_url
        config.llm.base_url = config.llm.base_url or "https://api.deepseek.com"

    # 3. 输入 API 密钥
    if not config.llm.api_key:
        env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
        existing_key = os.environ.get(env_api_key)

        if not existing_key:
            print(f"\n{'🔐 ' if emoji else ''}需要设置 API 密钥")
            print(f"   你也可以提前设置 {env_api_key} 环境变量跳过此步骤。\n")

            api_key = _prompt_for_api_key(provider)

            if not api_key:
                print(f"\n{'❌ ' if emoji else ''}未输入 API 密钥，无法启动。")
                print(f"提示: 可通过设置 {env_api_key} 环境变量跳过此步骤")
                sys.exit(1)

            config.llm.api_key = api_key

            # 询问是否保存到配置文件
            try:
                save_prompt = (
                    f"\n{'💾 ' if emoji else ''}是否将密钥保存到配置文件以便下次自动使用？(y/N): "
                )
                save = input(save_prompt).strip().lower()
                if save in ("y", "yes"):
                    config.save()
                    print(f"{'✅ ' if emoji else ''}密钥已保存到配置文件")
            except (EOFError, KeyboardInterrupt):
                pass
        else:
            # 环境变量中已有密钥
            config.llm.api_key = existing_key

    # 如果配置有变化，保存提供者和模型设置
    if is_first_run:
        try:
            config.save()
            print(f"\n{'✅ ' if emoji else ''}设置已保存到配置文件")
        except Exception:
            pass


def _handle_reset_key(agent: Agent) -> None:
    """处理 /reset-key 命令：重新设置 API 密钥。

    Args:
        agent: 当前 Agent 实例。
    """
    emoji = _supports_emoji()
    provider_info = PROVIDER_MODELS.get(agent.config.llm.provider, {})
    env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")

    print_message("system", "准备重新设置 API 密钥")

    api_key = _prompt_for_api_key(agent.config.llm.provider)

    if not api_key:
        print_message("error", "未输入 API 密钥，取消操作")
        return

    # 更新配置
    agent.config.llm.api_key = api_key

    # 询问是否保存到配置文件
    try:
        save_prompt = (
            f"\n{'💾 ' if emoji else ''}是否将密钥保存到配置文件以便下次自动使用？(y/N): "
        )
        save = input(save_prompt).strip().lower()
        if save in ("y", "yes"):
            agent.config.save()
            print_message("system", "密钥已保存到配置文件")
    except (EOFError, KeyboardInterrupt):
        pass

    # 重新初始化 LLM 提供者
    _reinit_llm(agent)
    print_message("system", "API 密钥已更新，可以继续聊天了 💫")


def _handle_switch_model(agent: Agent) -> None:
    """处理 /switch-model 命令：切换提供者和模型。

    Args:
        agent: 当前 Agent 实例。
    """
    emoji = _supports_emoji()
    print_message("system", "准备切换模型")

    # 选择提供者
    provider = _prompt_provider_selection()

    # 选择模型
    model = _prompt_model_selection(provider)

    # 如果是 openai-compatible，询问 base_url
    if provider == "openai-compatible":
        base_url = _prompt_base_url(provider)
        if base_url:
            agent.config.llm.base_url = base_url

    # 更新配置
    old_provider = agent.config.llm.provider
    agent.config.llm.provider = provider
    agent.config.llm.model = model

    # 如果切换了提供者，可能需要新的 API 密钥
    if provider != old_provider:
        provider_info = PROVIDER_MODELS.get(provider, {})
        env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
        existing_key = os.environ.get(env_api_key) or agent.config.llm.api_key

        if not existing_key:
            print_message(
                "system",
                f"切换提供者需要设置 {env_api_key}",
            )
            api_key = _prompt_for_api_key(provider)
            if api_key:
                agent.config.llm.api_key = api_key

    # 询问是否保存
    try:
        save_prompt = (
            f"\n{'💾 ' if emoji else ''}是否保存此设置以便下次自动使用？(y/N): "
        )
        save = input(save_prompt).strip().lower()
        if save in ("y", "yes"):
            agent.config.save()
            print_message("system", "设置已保存到配置文件")
    except (EOFError, KeyboardInterrupt):
        pass

    # 重新初始化 LLM
    try:
        _reinit_llm(agent)
        provider_label = PROVIDER_MODELS.get(provider, {}).get("label", provider)
        print_message(
            "system",
            f"已切换到 {provider_label} / {model} 💫",
        )
    except Exception as e:
        print_message("error", f"切换模型失败: {e}")


def _reinit_llm(agent: Agent) -> None:
    """重新初始化 Agent 的 LLM 提供者。

    根据当前配置重新创建 LLM 提供者实例。

    Args:
        agent: 当前 Agent 实例。
    """
    provider_type = agent.config.llm.provider
    provider_info = PROVIDER_MODELS.get(provider_type, {})
    env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")

    api_key = agent.config.llm.api_key or os.environ.get(env_api_key)
    base_url = agent.config.llm.base_url or os.environ.get(
        provider_info.get("env_base_url", ""), ""
    )

    agent.llm.initialize(
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        model=agent.config.llm.model,
    )


def cli_entry() -> None:
    """CLI 入口点（由 pyproject.toml 的 scripts 注册）。

    解析命令行参数，初始化配置和 Agent，进入交互或单次对话模式。
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} — 陪伴型 AI 智能体框架"
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
        help="LLM 提供者 (openai, anthropic, deepseek, openai-compatible)",
    )
    parser.add_argument(
        "--base-url", "-b",
        help="API 基础地址（用于兼容 OpenAI 格式的第三方服务）",
    )
    parser.add_argument(
        "--one-shot", "-o",
        help="单次对话模式: shuxin -o '你好'",
    )
    parser.add_argument(
        "--version", "-V",
        action="store_true",
        help="显示版本信息",
    )

    args = parser.parse_args()

    if args.version:
        print(f"{APP_NAME} v{VERSION}")
        return

    # 配置日志
    setup_logging(args.debug)

    # 加载配置
    try:
        config = Config.load(args.config)
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        sys.exit(1)

    # 命令行覆盖
    if args.provider:
        config.llm.provider = args.provider
    if args.model:
        config.llm.model = args.model
    if args.base_url:
        config.llm.base_url = args.base_url

    # 确保配置完整（交互式引导选择提供者、模型、API 密钥）
    _ensure_setup(config)

    # 初始化智能体
    agent = Agent(config)
    try:
        agent.initialize()
    except RuntimeError as e:
        print(f"❌ 初始化失败: {e}")
        provider_info = PROVIDER_MODELS.get(config.llm.provider, {})
        env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
        print(f"提示: 请确保已设置 {env_api_key} 环境变量或输入了有效的 API 密钥")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # 单次对话模式
    if args.one_shot:
        try:
            response = agent.chat(args.one_shot)
            print(response)
        except Exception as e:
            print(f"❌ 对话失败: {e}")
            sys.exit(1)
        return

    # 交互模式
    try:
        run_interactive(agent)
    finally:
        agent.shutdown()


if __name__ == "__main__":
    cli_entry()
