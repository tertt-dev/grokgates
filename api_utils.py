"""
API Utilities - Shared retry logic and connection handling
"""
import asyncio
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class APIClient:
    """Enhanced API client with robust retry logic"""
    
    def __init__(self, base_url: str, headers: Dict[str, str], timeout: float = 120.0):
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delays = {
            'connection': [15, 30, 60],  # Connection errors
            'server': [30, 60, 120],      # Server errors (5xx)
            'timeout': [10, 20, 40],      # Timeout errors
            'default': [5, 10, 20]        # Other errors
        }
    
    async def post(self, endpoint: str, json_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make POST request with intelligent retry logic"""
        
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    headers=self.headers,
                    timeout=httpx.Timeout(
                        self.timeout,
                        connect=30.0,
                        read=self.timeout,
                        write=30.0,
                        pool=30.0
                    ),
                    follow_redirects=True,
                    verify=True,
                    limits=httpx.Limits(
                        max_connections=10,
                        max_keepalive_connections=5,
                        keepalive_expiry=30.0
                    )
                ) as client:
                    response = await client.post(endpoint, json=json_data)
                    
                    # Check for server errors that might be temporary
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error: {response.status_code}",
                            request=response.request,
                            response=response
                        )
                    
                    response.raise_for_status()
                    return response.json()
                    
            except httpx.RemoteProtocolError as e:
                error_type = 'server'
                logger.warning(f"Server disconnected (attempt {attempt + 1}/{self.max_retries}): {e}")
                
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                error_type = 'connection'
                logger.warning(f"Connection failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                
            except httpx.ReadTimeout as e:
                error_type = 'timeout'
                logger.warning(f"Read timeout (attempt {attempt + 1}/{self.max_retries}): {e}")
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    error_type = 'server'
                    logger.warning(f"Server error {e.response.status_code} (attempt {attempt + 1}/{self.max_retries})")
                else:
                    # Client error (4xx), don't retry
                    logger.error(f"Client error {e.response.status_code}: {e.response.text}")
                    return None
                    
            except Exception as e:
                error_type = 'default'
                logger.error(f"Unexpected error (attempt {attempt + 1}/{self.max_retries}): {e}")
            
            # Don't sleep after the last attempt
            if attempt < self.max_retries - 1:
                delay = self.retry_delays[error_type][attempt]
                logger.info(f"Waiting {delay}s before retry...")
                await asyncio.sleep(delay)
        
        logger.error(f"All {self.max_retries} attempts failed for {endpoint}")
        return None

    async def stream_post(self, endpoint: str, json_data: Dict[str, Any]):
        """Make streaming POST request with retry logic"""
        
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    headers=self.headers,
                    timeout=httpx.Timeout(
                        self.timeout,
                        connect=30.0,
                        read=None,  # No read timeout for streaming
                        write=30.0,
                        pool=30.0
                    ),
                    follow_redirects=True,
                    verify=True
                ) as client:
                    async with client.stream('POST', endpoint, json=json_data) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_text():
                            yield chunk
                return  # Success
                
            except Exception as e:
                logger.warning(f"Stream error (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delays['default'][attempt])
                else:
                    raise