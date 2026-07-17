import logging
import time
from typing import Optional

from .http import feishu_request, is_retryable_error

logger = logging.getLogger(__name__)


class TokenManager:
    """管理飞书 tenant_access_token，每半小时自动刷新"""

    def __init__(self, app_id: str, app_secret: str, refresh_interval_seconds: int = 1800):
        """
        :param app_id: 飞书应用 App ID
        :param app_secret: 飞书应用 App Secret
        :param refresh_interval_seconds: token 刷新间隔（秒），默认 1800 秒（半小时）
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.refresh_interval = refresh_interval_seconds
        self._token: Optional[str] = None
        self._expire_time: float = 0

    def get_token(self) -> str:
        """获取有效的 tenant_access_token，如果过期则自动刷新"""
        if self._token and time.time() < self._expire_time:
            return self._token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}

        try:
            response = feishu_request("POST", url, json=payload, rate_limit=True)
            result = response.json()

            if result.get("code") != 0:
                raise Exception(f"获取 token 失败: {result.get('msg')}")

            self._token = result.get("tenant_access_token")
            self._expire_time = time.time() + self.refresh_interval
            logger.info("Tenant access token 刷新成功，有效期 %s 秒", self.refresh_interval)
            return self._token
        except Exception as e:
            if is_retryable_error(e):
                logger.error("获取 tenant_access_token 异常（已重试）: %s", e)
            else:
                logger.error("获取 tenant_access_token 异常: %s", e)
            raise

    def invalidate(self):
        """强制使 token 失效（用于测试或特殊场景）"""
        self._token = None
        self._expire_time = 0
