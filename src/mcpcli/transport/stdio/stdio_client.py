# transport/stdio/stdio_client.py
import json
import logging
import sys
import traceback
from contextlib import asynccontextmanager

import anyio
from anyio.streams.text import TextReceiveStream

from mcpcli.environment import get_default_environment
from mcpcli.messages.message_types.json_rpc_message import JSONRPCMessage
from mcpcli.transport.stdio.stdio_server_parameters import StdioServerParameters


@asynccontextmanager
async def stdio_client(server: StdioServerParameters):
    # 確保服務器命令存在
    if not server.command:
        raise ValueError("Server command must not be empty.")

    # 確保服務器參數是列表或元組
    if not isinstance(server.args, (list, tuple)):
        raise ValueError("Server arguments must be a list or tuple.")

    # 建立讀取和寫入流
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # 啟動子進程
    process = await anyio.open_process(
        [server.command, *server.args],
        env={**get_default_environment(), **(server.env or {})},
        stderr=sys.stderr,
    )

    # 服務器已啟動
    logging.debug(
        f"Subprocess started with PID {process.pid}, command: {server.command}"
    )

    # 創建一個任務從子進程的 stdout 讀取
    async def process_json_line(line: str, writer):
        try:
            logging.debug(f"Processing line: {line.strip()}")
            data = json.loads(line)

            # 解析 JSON
            logging.debug(f"Parsed JSON data: {data}")

            # 驗證 JSON-RPC 消息
            message = JSONRPCMessage.model_validate(data)
            logging.debug(f"Validated JSONRPCMessage: {message}")

            # 發送消息
            await writer.send(message)
        except json.JSONDecodeError as exc:
            # 不是有效的 JSON
            logging.error(f"JSON decode error: {exc}. Line: {line.strip()}")
        except Exception as exc:
            # 其他異常
            logging.error(f"Error processing message: {exc}. Line: {line.strip()}")
            logging.debug(f"Traceback:\n{traceback.format_exc()}")

    async def stdout_reader():
        """從服務器的 stdout 讀取 JSON-RPC 消息."""
        # 確保進程的 stdout 存在
        assert process.stdout, "Opened process is missing stdout"
        buffer = ""
        logging.debug("Starting stdout_reader")
        try:
            async with read_stream_writer:
                async for chunk in TextReceiveStream(process.stdout):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        if line.strip():
                            await process_json_line(line, read_stream_writer)
                if buffer.strip():
                    await process_json_line(buffer, read_stream_writer)
        except anyio.ClosedResourceError:
            logging.debug("Read stream closed.")
        except Exception as exc:
            logging.error(f"Unexpected error in stdout_reader: {exc}")
            logging.debug(f"Traceback:\n{traceback.format_exc()}")
            raise
        finally:
            logging.debug("Exiting stdout_reader")

    async def stdin_writer():
        """從寫入流發送 JSON-RPC 消息到服務器的 stdin."""
        # 確保進程的 stdin 存在
        assert process.stdin, "Opened process is missing stdin"
        logging.debug("Starting stdin_writer")
        try:
            async with write_stream_reader:
                async for message in write_stream_reader:
                    json_str = message.model_dump_json(exclude_none=True)
                    logging.debug(f"Sending: {json_str}")
                    await process.stdin.send((json_str + "\n").encode())
        except anyio.ClosedResourceError:
            logging.debug("Write stream closed.")
        except Exception as exc:
            logging.error(f"Unexpected error in stdin_writer: {exc}")
            logging.debug(f"Traceback:\n{traceback.format_exc()}")
            raise
        finally:
            logging.debug("Exiting stdin_writer")

    async def terminate_process():
        """優雅地終止子進程."""
        try:
            if process.returncode is None:  # 進程仍在運行
                logging.debug("Terminating subprocess...")
                process.terminate()
                with anyio.fail_after(5):
                    await process.wait()
            else:
                logging.info("Process already terminated.")
        except TimeoutError:
            logging.warning(
                "Process did not terminate gracefully. Forcefully killing it."
            )
            try:
                process.kill()
            except Exception as kill_exc:
                logging.error(f"Error killing process: {kill_exc}")
        except Exception as exc:
            logging.error(f"Error during process termination: {exc}")

    try:
        async with anyio.create_task_group() as tg, process:
            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)
            yield read_stream, write_stream

        # 退出任務組
        exit_code = await process.wait()
        logging.info(f"Process exited with code {exit_code}")
    except Exception as exc:
        # 其他異常
        logging.error(f"Unhandled error in TaskGroup: {exc}")
        logging.debug(f"Traceback:\n{traceback.format_exc()}")
        if hasattr(exc, "__cause__") and exc.__cause__:
            logging.debug(f"TaskGroup exception cause: {exc.__cause__}")
        raise
    finally:
        await terminate_process()
