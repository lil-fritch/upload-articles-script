
import requests
import json
import time
import logging
import asyncio
import aiohttp
from urllib.parse import urljoin
from langfuse import Langfuse
from .config import (
    LLM_API_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_EMBEDDING_MODEL,
    LLM_DELAY,
    IMAGE_API_URL,
    IMAGE_API_KEY,
    IMAGE_MODEL,
    IMAGE_POLL_INTERVAL,
    IMAGE_MAX_WAIT,
    settings,
)
from src.services.telegram_bot import telegram_bot
from src.utils.logger import setup_logger

logger = setup_logger("llm_client")

class LLMClient:
    def __init__(
        self,
        api_url=LLM_API_URL,
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
        embedding_model=LLM_EMBEDDING_MODEL,
        image_api_url=IMAGE_API_URL,
        image_api_key=IMAGE_API_KEY,
        image_model=IMAGE_MODEL,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.image_api_url = image_api_url
        self.image_api_key = image_api_key
        self.image_model = image_model
        self._consecutive_errors = 0
        
        # Initialize Langfuse if keys are present
        self.langfuse = None
        if settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY:
            try:
                self.langfuse = Langfuse(
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    host=settings.LANGFUSE_HOST
                )
                logger.info("Langfuse initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Langfuse: {e}")

    def _record_success(self):
        self._consecutive_errors = 0

    def _record_failure(self):
        self._consecutive_errors += 1
        if self._consecutive_errors >= 10:
            msg = "LLM failed 10 requests in a row. Stopping."
            asyncio.create_task(telegram_bot.send_message(msg))
            raise RuntimeError(msg)

    def generate(self, prompt, temperature=0.7):
        try:
            return asyncio.run(self.async_generate(prompt, temperature))
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self.async_generate(prompt, temperature))
            raise

    async def async_generate(self, prompt, temperature=0.7):
        await asyncio.sleep(LLM_DELAY)

        is_chat_completions = "/v1/chat/completions" in self.api_url or "/completions" in self.api_url
        headers = {
            "Content-Type": "application/json",
            "Connection": "close"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if is_chat_completions:
            endpoint = self.api_url
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a stateless AI. Forget all previous context. Focus ONLY on the current user request."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": temperature
            }
        else:
            endpoint = f"{self.api_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature
                }
            }

        timeout = aiohttp.ClientTimeout(total=300)
        for attempt in range(5):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.post(endpoint, json=payload) as response:
                        response.raise_for_status()
                        data = await response.json()
                        if is_chat_completions:
                            result_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        else:
                            result_text = data.get("response", "")

                        if self.langfuse:
                            try:
                                generation = self.langfuse.start_generation(
                                    name="llm_generation",
                                    model=self.model,
                                    input=prompt,
                                    output=result_text,
                                    metadata={"temperature": temperature, "attempt": attempt + 1, "endpoint": endpoint}
                                )
                                generation.end()
                            except Exception as lf_e:
                                logger.warning(f"Langfuse logging failed: {lf_e}")
                        self._record_success()
                        return result_text
            except asyncio.TimeoutError:
                try:
                    self._record_failure()
                except RuntimeError:
                    raise
                wait_time = (attempt + 1) * 5
                logger.warning(f"LLM Timeout (Attempt {attempt+1}/5). Cooling down {wait_time}s...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                try:
                    self._record_failure()
                except RuntimeError:
                    raise
                wait_time = (attempt + 1) * 2
                msg = f"LLM Error: {e} (Attempt {attempt+1}/5). Retrying in {wait_time}s..."
                logger.warning(msg)
                asyncio.create_task(telegram_bot.send_message(msg))
                await asyncio.sleep(wait_time)

        final_error = "LLM Generation failed after 5 attempts."
        logger.error(final_error)
        asyncio.create_task(telegram_bot.send_message(final_error))
        return ""

    def get_embeddings(self, text: str) -> list:
        try:
            return asyncio.run(self.async_get_embeddings(text))
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self.async_get_embeddings(text))
            raise

    async def async_get_embeddings(self, text: str) -> list:
        payload = {
            "model": self.embedding_model,
            "prompt": text
        }
        endpoint = f"{self.api_url}/api/embeddings"

        timeout = aiohttp.ClientTimeout(total=30)
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(endpoint, json=payload) as response:
                        response.raise_for_status()
                        data = await response.json()
                        self._record_success()
                        return data.get("embedding", [])
            except asyncio.TimeoutError:
                try:
                    self._record_failure()
                except RuntimeError:
                    raise
                logger.warning(f"Embedding Timeout (Attempt {attempt+1}/2). Retrying...")
                await asyncio.sleep(0.5)
            except Exception as e:
                try:
                    self._record_failure()
                except RuntimeError:
                    raise
                logger.warning(f"Embedding Error: {e}")
                if attempt == 1:
                    break
                await asyncio.sleep(0.5)
        return []

    def generate_image(self, prompt: str, max_wait: float | None = None) -> str:
        try:
            return asyncio.run(self.async_generate_image(prompt, max_wait=max_wait))
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self.async_generate_image(prompt, max_wait=max_wait))
            raise

    async def async_generate_image(self, prompt: str, max_wait: float | None = None) -> str:
        if not self.image_api_url:
            logger.warning("Image API URL not configured, skipping image generation.")
            return ""

        headers = {
            "Content-Type": "application/json",
            "Connection": "close"
        }
        if self.image_api_key:
            headers["Authorization"] = f"Bearer {self.image_api_key}"

        payload = {
            "model": self.image_model,
            "prompt": prompt
        }

        generation_url = f"{self.image_api_url.rstrip('/')}/v1/images/generations"
        poll_url_base = f"{self.image_api_url.rstrip('/')}/v1/tasks/"
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            # First session for submission - distinct from polling session because of timeout
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as submit_session:
                generation_url = f"{self.image_api_url.rstrip('/')}/v1/images/generations"
                async with submit_session.post(generation_url, json=payload) as response:
                    # Case 1: Synchronous response (URL immediately)
                    if response.status in (200, 201):
                        data = await response.json()
                        # Check if data is list of objects with url 
                        if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                             url = data["data"][0].get("url")
                             if url:
                                 return url
                        
                         # Check if task_id is present (Asynchronous)
                        task_id = data.get("task_id") or data.get("id")
                    
                    # Case 2: 202 Accepted (Asynchronous task)
                    elif response.status == 202:
                        data = await response.json()
                        task_id = data.get("task_id") or data.get("id")
                    else:
                        error_text = await response.text()
                        logger.error(f"Image generation submit failed ({response.status}): {error_text}")
                        return ""

            if not task_id:
                     # Maybe the first response contained the result directly in a different format?
                     # If not, fail.
                     logger.error(f"Image generation response missing task_id. Data: {data}")
                     return ""

            start = time.monotonic()
            max_wait = max_wait if max_wait is not None else IMAGE_MAX_WAIT
            logger.info(f"Image task started: {task_id} | max_wait={max_wait}s | poll={IMAGE_POLL_INTERVAL}s")
            
            poll_url_base = f"{self.image_api_url.rstrip('/')}/v1/tasks/"
            
            # Polling with a new session that persists or is created per request
            async with aiohttp.ClientSession(headers=headers) as poll_session:
                while True:
                    if time.monotonic() - start > max_wait:
                        logger.error(f"Image generation timed out after {max_wait}s. Task: {task_id}")
                        return ""

                    await asyncio.sleep(IMAGE_POLL_INTERVAL)

                    async with poll_session.get(f"{poll_url_base}{task_id}") as poll_response:
                        if poll_response.status not in (200, 201):
                            poll_text = await poll_response.text()
                            logger.error(f"Image task poll failed ({poll_response.status}): {poll_text}")
                            return ""
                        poll_data = await poll_response.json()

                    status = poll_data.get("status")
                    logger.info(f"IMAGE POLLING: Status={status} | TaskID={task_id} | Elapsed={time.monotonic() - start:.1f}s")
                    
                    if status == "completed" or status == "succeeded":
                        # Exo Labs / Flux format often returns 'result' object with 'url'
                        result = poll_data.get("result", {})
                        # Try different locations for the URL depending on provider format
                        result_url = result.get("url") if isinstance(result, dict) else poll_data.get("result_url")
                        
                        # Fallback: sometimes result is just the URL string
                        if not result_url and isinstance(result, str) and result.startswith("http"):
                             result_url = result

                        # Additional fallback for root-level result_url found in your logs
                        if not result_url:
                            result_url = poll_data.get("result_url")

                        if not result_url:
                             # Check 'output' field common in some replicate-like APIs
                             output = poll_data.get("output")
                             if output and isinstance(output, list) and len(output) > 0:
                                 result_url = output[0]
                        
                        if not result_url:
                            logger.error(f"Image task completed but result URL missing. Data: {poll_data}")
                            return ""
                            
                        # Handle relative URLs
                        if result_url.startswith("/"):
                             base = self.image_api_url.rstrip('/')
                             # If API is something like https://example.com/v1, we usually want https://example.com
                             # But here let's be simpler: if result is /images/..., join with base
                             
                             from urllib.parse import urlparse
                             parsed_api = urlparse(base)
                             # Construct base like https://hostname
                             host_base = f"{parsed_api.scheme}://{parsed_api.netloc}"
                             
                             return urljoin(host_base, result_url)
                        
                        return result_url

                    if status in ("failed", "error"):
                        logger.error(f"Image task failed: {poll_data}")
                        return ""
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return ""

    def download_image(self, image_url: str, dest_path: str) -> bool:
        try:
            return asyncio.run(self.async_download_image(image_url, dest_path))
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self.async_download_image(image_url, dest_path))
            raise

    async def async_download_image(self, image_url: str, dest_path: str) -> bool:
        if not image_url:
            return False

        timeout = aiohttp.ClientTimeout(total=60)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        logger.error(f"Image download failed ({response.status}): {image_url}")
                        return False
                    with open(dest_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Image download error: {e}")
            return False
