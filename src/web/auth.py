"""HTTP Basic Auth 中间件 — 可选的密码保护。

通过环境变量 BILI_SCRIBE_PASSWORD 设置密码。
未设置时，认证被跳过（兼容本地开发）。

生产部署建议通过 docker-compose environment 或 .env 设置密码。
"""

from __future__ import annotations

import base64
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth 中间件。

    检查请求的 Authorization header，与预设密码比对。
    密码未配置时跳过认证，保持向后兼容。
    """

    def __init__(self, app, password: str | None = None):
        super().__init__(app)
        self._password = password or os.environ.get("BILI_SCRIBE_PASSWORD", "")
        # 随机用户名，仅用于展示
        self._username = "admin"

    async def dispatch(self, request: Request, call_next):
        # 密码未配置 → 跳过认证
        if not self._password:
            return await call_next(request)

        # 健康检查端点不拦截（Docker healthcheck 需要）
        if request.url.path == "/api/v1/health":
            return await call_next(request)

        # 验证 Authorization header
        auth = request.headers.get("Authorization", "")
        if not self._verify(auth):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="bili-scribe", charset="UTF-8"'},
                content="Unauthorized",
            )

        return await call_next(request)

    def _verify(self, auth_header: str) -> bool:
        """验证 Basic Auth header。

        使用 secrets.compare_digest 防止时序攻击。

        参数：
            auth_header: Authorization header 值。

        返回：
            认证通过返回 True。
        """
        if not auth_header.startswith("Basic "):
            return False

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
            # 只验证密码，用户名任意
            return secrets.compare_digest(password, self._password)
        except Exception:
            return False