"""Check the installed release image without Google credentials or API calls."""

import importlib.metadata
import importlib.resources
import os
import shutil

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check():
    expected = os.environ["PACKAGE_VERSION"]
    actual = importlib.metadata.version("google-ads-mcp")
    if actual != expected:
        raise RuntimeError(f"Expected version {expected}, found {actual}")
    files = importlib.resources.files("ads_mcp")
    for filename in ("gaql_resources.txt", "tools_config.yaml"):
        if not files.joinpath(filename).is_file():
            raise RuntimeError(f"Missing package data: {filename}")
    if not shutil.which("google-ads-mcp"):
        raise RuntimeError("Missing google-ads-mcp entry point")
    with anyio.fail_after(60):
        async with stdio_client(
            StdioServerParameters(command="google-ads-mcp", env={})
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                if not tools.tools:
                    raise RuntimeError("Server returned no tools")
    print(f"Container smoke test passed: google-ads-mcp {actual}")


if __name__ == "__main__":
    anyio.run(check)
