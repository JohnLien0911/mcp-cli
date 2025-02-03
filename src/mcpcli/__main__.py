# src/__main__.py
import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import List

import anyio

# Rich imports
from rich import print
from rich.markdown import Markdown
from rich.panel import Panel

from mcpcli.chat_handler import handle_chat_mode, get_input
from mcpcli.config import load_config
from mcpcli.messages.send_ping import send_ping
from mcpcli.messages.send_prompts import send_prompts_list
from mcpcli.messages.send_resources import send_resources_list
from mcpcli.messages.send_initialize_message import send_initialize
from mcpcli.messages.send_call_tool import send_call_tool
from mcpcli.messages.send_tools_list import send_tools_list
from mcpcli.transport.stdio.stdio_client import stdio_client

# 預設設定檔路徑
DEFAULT_CONFIG_FILE = "server_config.json"

# 設定logging
logging.basicConfig(
    level=logging.CRITICAL,  # 設定logging等級為CRITICAL,只顯示嚴重錯誤
    format="%(asctime)s - %(levelname)s - %(message)s", # 設定logging格式
    stream=sys.stderr, # 設定logging輸出到標準錯誤流
)

def signal_handler(sig, frame):
    # 忽略後續的 SIGINT 信號 (Ctrl+C)
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # 美觀的退出訊息
    print("\n[bold red]Goodbye![/bold red]")

    # 立即強制終止程序
    os.kill(os.getpid(), signal.SIGKILL)

# 設定訊號處理器,處理 SIGINT 信號 (Ctrl+C)
signal.signal(signal.SIGINT, signal_handler)

async def handle_command(command: str, server_streams: List[tuple]) -> bool:
    """動態處理特定命令,支援多個伺服器。"""
    try:
        if command == "ping":
            print("[cyan]\nPinging Servers...[/cyan]") # 顯示ping伺服器訊息
            for i, (read_stream, write_stream) in enumerate(server_streams):
                result = await send_ping(read_stream, write_stream) # 發送ping訊息到伺服器
                server_num = i + 1
                if result:
                    ping_md = f"## Server {server_num} Ping Result\n\n✅ **Server is up and running**" # ping成功訊息
                    print(Panel(Markdown(ping_md), style="bold green")) # 顯示綠色成功訊息面板
                else:
                    ping_md = f"## Server {server_num} Ping Result\n\n❌ **Server ping failed**" # ping失敗訊息
                    print(Panel(Markdown(ping_md), style="bold red")) # 顯示紅色失敗訊息面板

        elif command == "list-tools":
            print("[cyan]\nFetching Tools List from all servers...[/cyan]") # 顯示獲取工具列表訊息
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_tools_list(read_stream, write_stream) # 發送獲取工具列表訊息
                tools_list = response.get("tools", []) # 從回應中獲取工具列表
                server_num = i + 1

                if not tools_list:
                    tools_md = (
                        f"## Server {server_num} Tools List\n\nNo tools available." # 沒有工具可用的訊息
                    )
                else:
                    tools_md = f"## Server {server_num} Tools List\n\n" + "\n".join(
                        [
                            f"- **{t.get('name')}**: {t.get('description', 'No description')}" # 工具名稱和描述
                            for t in tools_list
                        ]
                    )
                print(
                    Panel(
                        Markdown(tools_md),
                        title=f"Server {server_num} Tools", # 面板標題
                        style="bold cyan", # 面板樣式
                    )
                )

        elif command == "call-tool":
            tool_name = await get_input("[bold magenta]Enter tool name[/bold magenta]") # 提示使用者輸入工具名稱
            if not tool_name:
                print("[red]Tool name cannot be empty.[/red]") # 工具名稱為空錯誤訊息
                return True

            arguments_str = await get_input("[bold magenta]Enter tool arguments as JSON (e.g., {'key': 'value'})[/bold magenta]") # 提示使用者輸入工具參數JSON
            try:
                arguments = json.loads(arguments_str) # 解析JSON參數
            except json.JSONDecodeError as e:
                print(f"[red]Invalid JSON arguments format:[/red] {e}") # JSON格式錯誤訊息
                return True

            print(f"[cyan]\nCalling tool '{tool_name}' with arguments:\n[/cyan]") # 顯示呼叫工具訊息
            print(
                Panel(
                    Markdown(f"```json\n{json.dumps(arguments, indent=2)}\n```"), # 顯示JSON參數
                    style="dim", # 面板樣式
                )
            )

            for read_stream, write_stream in server_streams:
                result = await send_call_tool(tool_name, arguments, read_stream, write_stream) # 發送呼叫工具訊息
                if result.get("isError"):
                    # print(f"[red]Error calling tool:[/red] {result.get('error')}")
                    continue
                response_content = result.get("content", "No content") # 獲取工具回應內容
                try:
                    if response_content[0]['text'].startswith('Error:'): # 檢查回應內容是否為錯誤訊息
                        continue
                except:
                    pass
                print(
                    Panel(
                        Markdown(f"### Tool Response\n\n{response_content}"), # 顯示工具回應內容
                        style="green", # 面板樣式
                    )
                )

        elif command == "list-resources":
            print("[cyan]\nFetching Resources List from all servers...[/cyan]") # 顯示獲取資源列表訊息
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_resources_list(read_stream, write_stream) # 發送獲取資源列表訊息
                resources_list = response.get("resources", []) if response else None # 從回應中獲取資源列表
                server_num = i + 1

                if not resources_list:
                    resources_md = f"## Server {server_num} Resources List\n\nNo resources available." # 沒有資源可用的訊息
                else:
                    resources_md = f"## Server {server_num} Resources List\n"
                    for r in resources_list:
                        if isinstance(r, dict):
                            json_str = json.dumps(r, indent=2) # 將資源資訊轉換為JSON字串
                            resources_md += f"\n```json\n{json_str}\n```" # 顯示JSON格式資源資訊
                        else:
                            resources_md += f"\n- {r}" # 顯示資源名稱
                print(
                    Panel(
                        Markdown(resources_md),
                        title=f"Server {server_num} Resources", # 面板標題
                        style="bold cyan", # 面板樣式
                    )
                )

        elif command == "list-prompts":
            print("[cyan]\nFetching Prompts List from all servers...[/cyan]") # 顯示獲取提示列表訊息
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_prompts_list(read_stream, write_stream) # 發送獲取提示列表訊息
                prompts_list = response.get("prompts", []) if response else None # 從回應中獲取提示列表
                server_num = i + 1

                if not prompts_list:
                    prompts_md = (
                        f"## Server {server_num} Prompts List\n\nNo prompts available." # 沒有提示可用的訊息
                    )
                else:
                    prompts_md = f"## Server {server_num} Prompts List\n\n" + "\n".join(
                        [f"- {p}" for p in prompts_list] # 顯示提示名稱
                    )
                print(
                    Panel(
                        Markdown(prompts_md),
                        title=f"Server {server_num} Prompts", # 面板標題
                        style="bold cyan", # 面板樣式
                    )
                )

        elif command == "chat":
            provider = os.getenv("LLM_PROVIDER", "openai") # 獲取LLM提供者環境變數,預設為openai
            model = os.getenv("LLM_MODEL", "gpt-4o-mini") # 獲取LLM模型環境變數,預設為gpt-4o-mini

            # 先清除螢幕
            if sys.platform == "win32":
                os.system("cls") # Windows系統清除螢幕指令
            else:
                os.system("clear") # 其他系統清除螢幕指令

            chat_info_text = (
                "Welcome to the Chat!\n\n"
                f"**Provider:** {provider}  |  **Model:** {model}\n\n" # 聊天模式資訊
                "Type 'exit' to quit." # 退出聊天模式提示
            )

            print(
                Panel(
                    Markdown(chat_info_text),
                    style="bold cyan", # 面板樣式
                    title="Chat Mode", # 面板標題
                    title_align="center", # 標題對齊方式
                )
            )
            await handle_chat_mode(server_streams, provider, model) # 進入聊天模式處理函式

        elif command in ["quit", "exit"]:
            print("\n[bold red]Goodbye![/bold red]") # 退出訊息
            return False # 返回False,結束互動模式迴圈

        elif command == "clear":
            if sys.platform == "win32":
                os.system("cls") # Windows系統清除螢幕指令
            else:
                os.system("clear") # 其他系統清除螢幕指令

        elif command == "help":
            help_md = """
# Available Commands

- **ping**: Check if server is responsive # 檢查伺服器是否回應
- **list-tools**: Display available tools # 顯示可用工具
- **list-resources**: Display available resources # 顯示可用資源
- **list-prompts**: Display available prompts # 顯示可用提示
- **chat**: Enter chat mode # 進入聊天模式
- **clear**: Clear the screen # 清除螢幕
- **help**: Show this help message # 顯示此幫助訊息
- **quit/exit**: Exit the program # 退出程式

**Note:** Commands use dashes (e.g., `list-tools` not `list tools`). # 注意:命令使用 dashes (例如:list-tools 而不是 list tools)
"""
            print(Panel(Markdown(help_md), style="yellow")) # 顯示幫助訊息面板

        else:
            print(f"[red]\nUnknown command: {command}[/red]") # 未知命令錯誤訊息
            print("[yellow]Type 'help' for available commands[/yellow]") # 顯示幫助提示
    except Exception as e:
        print(f"\n[red]Error executing command:[/red] {e}") # 執行命令錯誤訊息

    return True # 返回True,繼續互動模式迴圈

async def interactive_mode(server_streams: List[tuple]):
    """以互動模式執行 CLI,支援多個伺服器。"""
    welcome_text = """
# Welcome to the Interactive MCP Command-Line Tool (Multi-Server Mode)

Type 'help' for available commands or 'quit' to exit.
"""
    print(Panel(Markdown(welcome_text), style="bold cyan")) # 顯示歡迎訊息面板

    while True: # 互動模式主迴圈
        try:
            command = await get_input("[bold green]\n>[/bold green]") # 提示使用者輸入命令
            command = command.lower() # 將命令轉換為小寫
            if not command:
                continue # 如果命令為空,則繼續下一次迴圈
            should_continue = await handle_command(command, server_streams) # 處理命令
            if not should_continue:
                return # 如果命令指示退出,則返回
        except EOFError: # 處理 EOFError (End of File Error)
            break # 退出迴圈
        except Exception as e: # 捕獲其他異常
            print(f"\n[red]Error:[/red] {e}") # 顯示錯誤訊息

class GracefulExit(Exception):
    """自訂例外處理,用於優雅退出。"""
    pass

async def run(config_path: str, server_names: List[str], command: str = None) -> None:
    """主函式,管理伺服器初始化、通訊和關閉。"""
    # 在渲染任何內容之前清除螢幕
    if sys.platform == "win32":
        os.system("cls") # Windows系統清除螢幕指令
    else:
        os.system("clear") # 其他系統清除螢幕指令

    # 載入伺服器設定並為所有伺服器建立連線
    server_streams = [] # 儲存伺服器stream的列表
    context_managers = [] # 儲存context manager的列表
    for server_name in server_names: # 迭代伺服器名稱列表
        server_params = await load_config(config_path, server_name) # 載入伺服器設定

        # 為每個伺服器建立 stdio 通訊
        cm = stdio_client(server_params) # 建立stdio client context manager
        (read_stream, write_stream) = await cm.__aenter__() # 進入context manager,獲取stream
        context_managers.append(cm) # 添加context manager到列表
        server_streams.append((read_stream, write_stream)) # 添加stream到列表

        init_result = await send_initialize(read_stream, write_stream) # 發送初始化訊息
        if not init_result: # 如果初始化失敗
            print(f"[red]Server initialization failed for {server_name}[/red]") # 顯示伺服器初始化失敗訊息
            return # 退出函式

    try:
        if command:
            # 單一命令模式
            await handle_command(command, server_streams) # 處理單一命令
        else:
            # 互動模式
            await interactive_mode(server_streams) # 進入互動模式
    finally:
        # 清理所有 streams
        for cm in context_managers: # 迭代context manager列表
            with anyio.move_on_after(1):  # 等待最多 1 秒
                await cm.__aexit__() # 退出context manager,清理stream

def cli_main():
    # 設定命令列解析器
    parser = argparse.ArgumentParser(description="MCP Command-Line Tool") # 建立ArgumentParser物件

    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE, # 預設設定檔路徑
        help="Path to the JSON configuration file containing server details.", # 幫助訊息
    )

    parser.add_argument(
        "--server",
        action="append", # 允許重複添加參數
        dest="servers", # 參數儲存的目標變數名
        help="Server configuration(s) to use. Can be specified multiple times.", # 幫助訊息
        default=[], # 預設值為空列表
    )

    parser.add_argument(
        "--all",
        action="store_true", # 設定為store_true,當命令列中出現 --all 時,值為 True
        dest="all", # 參數儲存的目標變數名
        default=False # 預設值為 False
    )

    parser.add_argument(
        "command",
        nargs="?", # 參數數量為0或1
        choices=["ping", "list-tools", "list-resources", "list-prompts"], # 參數可選值列表
        help="Command to execute (optional - if not provided, enters interactive mode).", # 幫助訊息
    )

    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "ollama","vllm"], # 參數可選值列表
        default="openai", # 預設值為 openai
        help="LLM provider to use. Defaults to 'openai'.", # 幫助訊息
    )

    parser.add_argument(
        "--model",
        help=("Model to use. Defaults to 'gpt-4o-mini' for openai, 'claude-3-5-haiku-latest' for anthropic and 'qwen2.5-coder' for ollama"), # 幫助訊息
    )

    args = parser.parse_args() # 解析命令列參數

    # 根據提供者設定預設模型
    model = args.model or (
        "gpt-4o-mini" if args.provider == "openai"
        else "claude-3-5-haiku-latest" if args.provider == "anthropic"
        else "qwen2.5-coder"
    )
    os.environ["LLM_PROVIDER"] = args.provider # 設定LLM提供者環境變數
    os.environ["LLM_MODEL"] = model # 設定LLM模型環境變數

    try:
        if args.all: # 如果使用了 --all 參數
            with open(args.config_file, 'r', encoding='UTF-8') as f: # 開啟設定檔
                args.servers=list(json.load(f)['mcpServers'].keys())                
        result = anyio.run(run, args.config_file, args.servers, args.command) # 執行主函式 run
        sys.exit(result) # 退出程式,返回執行結果
    except Exception as e: # 捕獲異常
        print(f"[red]Error occurred:[/red] {e}") # 顯示錯誤訊息
        sys.exit(1) # 退出程式,返回錯誤碼1

if __name__ == "__main__":
    cli_main() # 如果是直接執行此腳本,則執行 cli_main 函式
