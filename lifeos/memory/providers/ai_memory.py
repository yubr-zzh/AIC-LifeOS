"""Read-only, explicitly project-scoped adapter for the ai-memory HTTP API."""

import ipaddress
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class AiMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiMemoryProjectConfig:
    endpoint: str
    project_map: dict
    api_token: str | None = None
    timeout_seconds: float = 3.0

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        endpoint = env.get("LIFEOS_AIMEMORY_ENDPOINT", "").strip()
        raw_map = env.get("LIFEOS_AIMEMORY_PROJECT_MAP", "").strip()
        token = env.get("LIFEOS_AIMEMORY_API_TOKEN", "").strip() or None
        configured = bool(endpoint or raw_map or token)
        if not configured:
            return None
        if not endpoint or not raw_map:
            raise ValueError(
                "incomplete ai-memory configuration; endpoint and explicit project map are required"
            )
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("LIFEOS_AIMEMORY_ENDPOINT must be an origin URL without a path")
        if parsed.query or parsed.fragment:
            raise ValueError("LIFEOS_AIMEMORY_ENDPOINT cannot include a query or fragment")
        host = (parsed.hostname or "").lower()
        is_loopback = host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("LifeOS ai-memory adapter only permits a loopback server in this phase")
        try:
            project_map = json.loads(raw_map)
        except json.JSONDecodeError as exc:
            raise ValueError("LIFEOS_AIMEMORY_PROJECT_MAP must be valid JSON") from exc
        if not isinstance(project_map, dict) or not project_map:
            raise ValueError("LIFEOS_AIMEMORY_PROJECT_MAP must be a non-empty object")
        for lifeos_project_id, target in project_map.items():
            if (
                not isinstance(lifeos_project_id, str)
                or not lifeos_project_id.strip()
                or not isinstance(target, dict)
                or not isinstance(target.get("workspace"), str)
                or not target["workspace"].strip()
                or not isinstance(target.get("project"), str)
                or not target["project"].strip()
            ):
                raise ValueError("each ai-memory mapping requires workspace and project strings")
        timeout = float(env.get("LIFEOS_AIMEMORY_TIMEOUT_SECONDS", "3"))
        if timeout <= 0:
            raise ValueError("LIFEOS_AIMEMORY_TIMEOUT_SECONDS must be positive")
        return cls(
            endpoint=endpoint.rstrip("/"),
            project_map=project_map,
            api_token=token,
            timeout_seconds=timeout,
        )


class AiMemoryProjectAdapter:
    """Project evidence reader. It never writes or searches across projects."""

    def __init__(self, config: AiMemoryProjectConfig, transport=None, *, max_pages=3, max_chars=6000):
        self.config = config
        self._transport = transport or self._http_get
        self.max_pages = max(1, min(int(max_pages), 5))
        self.max_chars = max(500, min(int(max_chars), 12000))

    def _http_get(self, url, headers):
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.load(response)
        except HTTPError as exc:
            raise AiMemoryError(f"ai-memory request failed: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AiMemoryError(f"ai-memory request failed: {type(exc).__name__}") from exc

    def _get(self, path, query=None):
        url = self.config.endpoint + path
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        result = self._transport(url, headers)
        if not isinstance(result, (dict, list)):
            raise AiMemoryError("ai-memory returned an invalid response")
        return result

    def retrieve(self, query, scope=None, limit=None):
        """Retrieve bounded pages for one explicitly mapped project scope."""
        if not isinstance(query, str) or not query.strip() or not isinstance(scope, dict):
            return []
        if scope.get("kind") != "project":
            return []
        lifeos_project_id = scope.get("project_id")
        target = self.config.project_map.get(lifeos_project_id)
        if not isinstance(target, dict):
            return []
        workspace = target["workspace"]
        project = target["project"]
        page_limit = self.max_pages if limit is None else max(1, min(int(limit), self.max_pages))
        hits = self._get(
            "/api/v1/search",
            {"q": query.strip(), "workspace": workspace, "project": project, "limit": page_limit},
        )
        if not isinstance(hits, list):
            raise AiMemoryError("ai-memory search response must be an array")

        evidence = []
        seen_paths = set()
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            if hit.get("workspace") != workspace or hit.get("project") != project:
                continue
            page_path = hit.get("path")
            if not self._valid_page_path(page_path) or page_path in seen_paths:
                continue
            seen_paths.add(page_path)
            encoded_path = "/".join(quote(part, safe="") for part in page_path.split("/"))
            page = self._get(
                f"/api/v1/workspaces/{quote(workspace, safe='')}/projects/{quote(project, safe='')}/pages/{encoded_path}"
            )
            if not isinstance(page, dict):
                continue
            if page.get("project") != project or page.get("path") != page_path:
                continue
            body = page.get("body_markdown")
            if not isinstance(body, str) or not body.strip():
                continue
            evidence.append(
                {
                    "provider": "ai-memory",
                    "project_id": lifeos_project_id,
                    "title": str(page.get("title") or hit.get("title") or page_path),
                    "kind": str(page.get("kind") or hit.get("kind") or "page"),
                    "path": page_path,
                    "content": body[: self.max_chars],
                    "source_ref": {
                        "provider": "ai-memory",
                        "workspace": workspace,
                        "project": project,
                        "path": page_path,
                    },
                    "scope": {"kind": "project", "project_id": lifeos_project_id},
                }
            )
        return evidence

    @staticmethod
    def _valid_page_path(value):
        if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
            return False
        normalized = value.replace("\\", "/")
        return all(part not in {"", ".", ".."} for part in normalized.split("/")) and "\\" not in value
