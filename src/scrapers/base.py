"""PulseBalanços - Classe Base Abstrata para Scrapers Oficiais."""

from __future__ import annotations

import abc
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import UnifiedStatementRecord

logger = logging.getLogger("pulsebalancos.scrapers.base")


class BaseScraper(abc.ABC):
    """Classe base resiliente para scrapers e extratores de dados públicos."""

    def __init__(
        self,
        name: str,
        cache_dir: Optional[Path] = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        self.name = name
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or Path("data/metadata"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"{name}_http_cache.json"
        self._http_cache: Dict[str, Dict[str, Any]] = self._load_cache()

        self.session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"],
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {
                "User-Agent": f"PulseDataLabs-PulseBalancos/{self.name} (+https://github.com/PulseDataLabs)",
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("[%s] Falha ao carregar cache de HTTP: %s", self.name, e)
        return {}

    def _save_cache(self) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._http_cache, f, indent=2)
        except Exception as e:
            logger.warning("[%s] Falha ao salvar cache de HTTP: %s", self.name, e)

    def download_in_memory(self, url: str, force: bool = False) -> Tuple[Optional[bytes], bool]:
        """Faz download em memória com suporte a ETag / If-Modified-Since e cache local."""
        raw_dir = self.cache_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.md5(url.encode()).hexdigest()
        raw_file = raw_dir / f"{url_hash}.bin"

        headers: Dict[str, str] = {}
        cached_info = self._http_cache.get(url, {})

        if not force and raw_file.exists():
            if cached_info.get("etag"):
                headers["If-None-Match"] = cached_info["etag"]
            if cached_info.get("last_modified"):
                headers["If-Modified-Since"] = cached_info["last_modified"]

        try:
            resp = self.session.get(url, headers=headers, stream=True, timeout=self.timeout)

            if resp.status_code == 304 and raw_file.exists():
                logger.info("[%s] HTTP 304 (Cache Hit): %s", self.name, url)
                return raw_file.read_bytes(), True

            resp.raise_for_status()
            content = resp.content

            # Persiste cópia temporária no cache local
            try:
                raw_file.write_bytes(content)
            except Exception:
                pass

            self._http_cache[url] = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "bytes": len(content),
            }
            self._save_cache()
            return content, False

        except Exception as e:
            logger.error("[%s] Erro na requisição para %s: %s", self.name, url, e)
            if raw_file.exists():
                logger.info("[%s] Usando cópia local em cache após falha de rede.", self.name)
                return raw_file.read_bytes(), True
            raise

    @abc.abstractmethod
    def extract_year(self, year: int) -> Iterator[UnifiedStatementRecord]:
        """Extrai todas as demonstrações contábeis do ano de exercício especificado."""
        pass
