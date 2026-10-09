"""Expose exactly three functions via the official MCP SDK over local stdio."""
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from policy import DecisionStore, Review


def main():
    application = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    store = DecisionStore(application, Path(sys.argv[2]))
    mcp = FastMCP("application-review")

    @mcp.tool()
    def advance_to_interview(review: Review) -> dict:
        """Record interview advancement locally after trusted policy validation."""
        return store.execute("advance_to_interview", review.model_dump())

    @mcp.tool()
    def reject(review: Review) -> dict:
        """Queue a rejection as waiting for human approval; never reject autonomously."""
        return store.execute("reject", review.model_dump())

    @mcp.tool()
    def request_more_info(review: Review) -> dict:
        """Record missing-information or suspicious-content review locally."""
        return store.execute("request_more_info", review.model_dump())

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
