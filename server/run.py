"""Container entry point."""
import os
import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "mcp_server:create_app",
        app_dir=os.path.dirname(__file__),
        factory=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )
