import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, question: str) -> list[float]:
        ...


class LocalEmbedder:
    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name)
        self.dimensions = self._model.get_sentence_embedding_dimension()
        e5 = "e5" in model_name.lower()
        self._doc_prefix, self._query_prefix = ("passage: ", "query: ") if e5 else ("", "")

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=self.batch_size,
                                     normalize_embeddings=True, show_progress_bar=len(texts) > 64)
        return [v.tolist() for v in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self._doc_prefix + t for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self._query_prefix + question])[0]


class OpenAICompatibleEmbedder:
    URLS = {"openai": "https://api.openai.com/v1/embeddings",
            "openrouter": "https://openrouter.ai/api/v1/embeddings"}

    def __init__(self, provider: str, model_name: str, api_key: str, batch_size: int = 64) -> None:
        if not api_key:
            raise RuntimeError(f"Missing API key for provider '{provider}' in .env")
        self.url = self.URLS[provider]
        self.model_name = model_name
        self.batch_size = batch_size
        self._key = api_key
        self.total_tokens = 0
        self.dimensions = len(self._post(["dimension probe"])[0])

    def _post(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model_name, "input": texts}).encode()
        request = urllib.request.Request(self.url, data=body, headers={
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Embedding API error {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc
        if "data" not in payload:
            raise RuntimeError(f"Embedding API returned no data: {str(payload)[:500]}")
        self.total_tokens += int(payload.get("usage", {}).get("prompt_tokens", 0))
        return [item["embedding"] for item in sorted(payload["data"], key=lambda d: d["index"])]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._post(texts[i:i + self.batch_size]))
        return out

    def embed_query(self, question: str) -> list[float]:
        return self._post([question])[0]


class GeminiEmbedder:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
    BATCH = 100

    def __init__(self, model_name: str, api_key: str, dimensions: int, max_per_minute: int = 100) -> None:
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY (in .env or environment)")
        self.model_name = model_name
        self.dimensions = dimensions
        self._key = api_key
        self.max_per_minute = max_per_minute
        self._sent: list[tuple[float, int]] = []
        got = len(self._post(["dimension probe"], "RETRIEVAL_QUERY")[0])
        if got != dimensions:
            raise RuntimeError(f"{model_name} returned {got} dims, expected {dimensions}")

    def _throttle(self, n: int) -> None:
        while True:
            now = time.monotonic()
            self._sent = [(t, k) for t, k in self._sent if now - t < 60]
            if sum(k for _, k in self._sent) + n <= self.max_per_minute:
                self._sent.append((now, n))
                return
            time.sleep(60 - (now - self._sent[0][0]) + 0.5)

    def _post(self, texts: list[str], task: str) -> list[list[float]]:
        body = json.dumps({"requests": [{
            "model": f"models/{self.model_name}", "content": {"parts": [{"text": t}]},
            "taskType": task, "outputDimensionality": self.dimensions} for t in texts]}).encode()
        request = urllib.request.Request(self.URL.format(model=self.model_name), data=body, headers={
            "x-goog-api-key": self._key, "Content-Type": "application/json"})
        for attempt in range(6):
            self._throttle(len(texts))
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return [e["values"] for e in json.load(response)["embeddings"]]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                if "PerDay" in detail:
                    raise RuntimeError("Gemini daily quota reached. Chunks stored so far are kept; "
                                       "re-run later to continue.\n" + detail[:500]) from exc
                if exc.code in (429, 503) and attempt < 5:
                    match = re.search(r'"retryDelay":\s*"(\d+)', detail)
                    wait = int(match.group(1)) + 1 if match else 2 ** attempt * 5
                    print(f"  Gemini {exc.code}, retry {attempt + 1}/5 in {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Gemini API error {exc.code}: {detail[:500]}") from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        size = min(self.BATCH, self.max_per_minute)
        for i in range(0, len(texts), size):
            out.extend(self._post(texts[i:i + size], "RETRIEVAL_DOCUMENT"))
        return out

    def embed_query(self, question: str) -> list[float]:
        return self._post([question], "RETRIEVAL_QUERY")[0]


def make_embedder() -> Embedder:
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini").strip().lower()
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    if provider == "gemini":
        dims = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
        per_minute = int(os.getenv("EMBEDDING_MAX_PER_MINUTE", "100"))
        return GeminiEmbedder(model or "gemini-embedding-001", os.getenv("GEMINI_API_KEY", ""), dims, per_minute)
    if provider == "local":
        return LocalEmbedder(model or "intfloat/multilingual-e5-small")
    if provider in OpenAICompatibleEmbedder.URLS:
        if not model:
            raise RuntimeError("Set EMBEDDING_MODEL in .env for API providers")
        key = os.getenv(f"{provider.upper()}_API_KEY", "")
        return OpenAICompatibleEmbedder(provider, model, key)
    raise RuntimeError(f"Unknown EMBEDDING_PROVIDER '{provider}' (use gemini, openai, openrouter or local)")
