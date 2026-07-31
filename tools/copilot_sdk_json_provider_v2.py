#!/usr/bin/env python3
from __future__ import annotations

import os
import time
import uuid
from typing import Any

try:
    import copilot_sdk_json_provider as base
except ModuleNotFoundError:
    from tools import copilot_sdk_json_provider as base
from copilot.session import PermissionHandler


async def _call_once_with_configured_idle_timeout(
    self: base.CopilotSDKJsonProvider,
    *,
    prompt: str,
    model: str,
    image_data_uri: str | None,
    reasoning_effort: str,
    idle_timeout: float,
) -> str:
    """Call one isolated session without the SDK's 60-second default idle limit."""
    if self._client is None:
        raise RuntimeError("Copilot SDK client is not started")
    session_id = f"v082-{uuid.uuid4().hex}"
    session = await self._client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        model=model,
        session_id=session_id,
        reasoning_effort=reasoning_effort,
        available_tools=[],
        enable_config_discovery=False,
    )
    try:
        attachments: list[dict[str, Any]] = []
        if image_data_uri and image_data_uri.startswith("data:image/") and "," in image_data_uri:
            header, payload = image_data_uri.split(",", 1)
            mime_type = header[5:].split(";", 1)[0]
            attachments.append({
                "type": "blob",
                "data": payload,
                "mimeType": mime_type,
                "displayName": (
                    "source-figure.jpg" if mime_type == "image/jpeg" else "source-figure.png"
                ),
            })
        response = await session.send_and_wait(
            prompt,
            attachments=attachments,
            timeout=idle_timeout,
        )
        if response is None or not getattr(response, "data", None):
            raise RuntimeError("Copilot SDK returned no assistant response")
        content = str(getattr(response.data, "content", "") or "").strip()
        if not content:
            raise RuntimeError("Copilot SDK returned an empty assistant response")
        return content
    finally:
        try:
            await session.disconnect()
        finally:
            try:
                if self._client is not None:
                    await self._client.delete_session(session_id)
            except Exception:
                pass


def call_text_with_configured_idle_timeout(
    self: base.CopilotSDKJsonProvider,
    *,
    prompt: str,
    model: str,
    image_data_uri: str | None = None,
    retries: int = 3,
    timeout: float | None = None,
) -> str:
    reasoning_effort = os.environ.get("V082_REASONING_EFFORT", "high")
    total_timeout = timeout or float(
        os.environ.get("V082_COPILOT_COMPONENT_TIMEOUT_SECONDS", "420")
    )
    idle_timeout = float(
        os.environ.get(
            "V082_COPILOT_IDLE_TIMEOUT_SECONDS",
            str(max(120.0, total_timeout - 45.0)),
        )
    )
    if idle_timeout >= total_timeout:
        idle_timeout = max(60.0, total_timeout - 30.0)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return self._submit(
                _call_once_with_configured_idle_timeout(
                    self,
                    prompt=prompt,
                    model=model,
                    image_data_uri=image_data_uri,
                    reasoning_effort=reasoning_effort,
                    idle_timeout=idle_timeout,
                ),
                timeout=total_timeout,
            )
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            try:
                self.recycle()
            except Exception:
                base.invalidate_provider(self)
            time.sleep(min(45, 6 * attempt))
    raise RuntimeError(
        f"Copilot SDK request failed after {retries} attempts: {last_error}"
    ) from last_error


base.CopilotSDKJsonProvider.call_text = call_text_with_configured_idle_timeout

CopilotSDKJsonProvider = base.CopilotSDKJsonProvider
call_json = base.call_json
compatible_call_model_json = base.compatible_call_model_json
provider = base.provider
invalidate_provider = base.invalidate_provider
parse_json_response = base.parse_json_response
