from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class QQBotError(RuntimeError):
    pass


@dataclass
class AccessToken:
    token: str
    expires_at: float


class QQBotClient:
    token_url = "https://bots.qq.com/app/getAppAccessToken"
    api_base = "https://api.sgroup.qq.com"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: AccessToken | None = None

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token.expires_at:
            return self._token.token
        payload = {"appId": self.app_id, "clientSecret": self.app_secret}
        data = self._request_json("POST", self.token_url, payload, auth=False)
        token = data.get("access_token")
        if not token:
            raise QQBotError(f"Access token response missing access_token: {data}")
        expires_in = int(data.get("expires_in", 7200))
        self._token = AccessToken(str(token), time.time() + expires_in - 60)
        return self._token.token

    def send_c2c_message(
        self,
        openid: str,
        content: str,
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> dict:
        body: dict[str, object] = {"msg_type": 0, "content": content}
        if msg_id:
            body["msg_id"] = msg_id
        if msg_seq is not None:
            body["msg_seq"] = msg_seq
        return self._request_json(
            "POST",
            f"{self.api_base}/v2/users/{openid}/messages",
            body,
            auth=True,
        )

    def get_gateway_url(self) -> str:
        data = self._request_json("GET", f"{self.api_base}/gateway", {}, auth=True)
        url = data.get("url")
        if not url:
            raise QQBotError(f"Gateway response missing url: {data}")
        return str(url)

    def _request_json(self, method: str, url: str, payload: dict, auth: bool) -> dict:
        data = None if method == "GET" else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"QQBot {self.get_access_token()}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise QQBotError(f"QQ API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise QQBotError(f"QQ API network error: {exc}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QQBotError(f"QQ API returned non-JSON: {raw[:300]}") from exc
        if not isinstance(parsed, dict):
            raise QQBotError(f"QQ API returned unexpected JSON: {parsed}")
        return parsed
