from __future__ import annotations

from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class NFIUClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        client_certificate: Optional[str] = None,
        private_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_cert = client_certificate
        self.private_key = private_key

        if client_certificate and private_key:
            self.client = httpx.AsyncClient(cert=(client_certificate, private_key), timeout=60.0)
        else:
            self.client = httpx.AsyncClient(timeout=60.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def submit_report(self, xml_content: str, attachments: Optional[List[Dict]] = None) -> Dict:
        url = f"{self.base_url}/api/v1/reports/submit"
        files = {"xml_report": ("report.xml", xml_content, "application/xml")}
        if attachments:
            for idx, attachment in enumerate(attachments):
                files[f"attachment_{idx}"] = (
                    attachment["filename"],
                    attachment["content"],
                    attachment.get("content_type", "application/octet-stream"),
                )
        headers = {"X-API-Key": self.api_key}
        res = await self.client.post(url, files=files, headers=headers)
        res.raise_for_status()
        return res.json()

    async def check_status(self, submission_id: str) -> Dict:
        url = f"{self.base_url}/api/v1/reports/status/{submission_id}"
        res = await self.client.get(url, headers={"X-API-Key": self.api_key})
        res.raise_for_status()
        return res.json()

    async def close(self) -> None:
        await self.client.aclose()

