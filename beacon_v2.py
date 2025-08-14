"""
Beacon v2.0 - Improved beacon system with strict JSON formatting
Reliable Twitter/X data collection with consistent output
"""
import asyncio
import httpx
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import logging
import re
import config
from redis_manager import RedisManager
from proposal_extractor import ProposalExtractor, Proposal
from urge_engine import UrgeEngine
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class BeaconV2:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.proposal_extractor = ProposalExtractor(redis_manager)
        self.urge_engine = UrgeEngine(redis_manager)
        self.api_key = config.GROK_API_KEY
        self.base_url = "https://api.x.ai/v1"
        self.phase_start_time = datetime.now()
        self.current_phase = "WORLD_SCAN"
        self.rate_limited_until: Optional[datetime] = None
        self._last_slot_run: Optional[int] = None
        
    def _extract_citations(self, api_result: Dict[str, Any]) -> List[str]:
        """Extract citations (list of URL strings) from API result - ONLY valid X/Twitter URLs."""
        urls: List[str] = []
        try:
            # Top-level citations list of strings (PRIMARY SOURCE)
            top_citations = api_result.get('citations', [])
            logger.debug(f"Found {len(top_citations)} top-level citations")
            for c in top_citations:
                if isinstance(c, str):
                    urls.append(c)
            
            # Choice-level message citations (SECONDARY SOURCE)
            for ch in (api_result.get('choices') or []):
                msg = ch.get('message') or {}
                msg_citations = msg.get('citations', [])
                if msg_citations:
                    logger.debug(f"Found {len(msg_citations)} message-level citations")
                for c in msg_citations:
                    if isinstance(c, str):
                        urls.append(c)
        except Exception as e:
            logger.error(f"Error extracting citations: {e}")
            
        # Filter for valid X/Twitter status URLs and dedup
        seen: set[str] = set()
        out: List[str] = []
        for u in urls:
            if u not in seen:
                if self._is_valid_x_status_url(u):
                    seen.add(u)
                    out.append(u)
                else:
                    logger.debug(f"Filtered out non-X URL: {u}")
        
        logger.info(f"Extracted {len(out)} valid X/Twitter citations from {len(urls)} total URLs")
        return out

    def _is_valid_x_status_url(self, url: Optional[str]) -> bool:
        """Return True only for real X/Twitter status URLs."""
        if not url or not isinstance(url, str):
            return False
        try:
            parsed = urlparse(url.strip())
            host = (parsed.netloc or '').lower()
            path_parts = [p for p in (parsed.path or '').split('/') if p]
            
            # Check if it's an X/Twitter domain
            is_x_domain = host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
            
            # Check if it's a status URL (format: /username/status/id)
            is_status_url = (
                len(path_parts) >= 3 and 
                path_parts[1] == 'status' and 
                path_parts[2].isdigit()
            )
            
            result = is_x_domain and is_status_url
            if not result:
                logger.debug(f"Invalid X URL: {url} (domain:{is_x_domain}, status:{is_status_url})")
            return result
        except Exception as e:
            logger.debug(f"Error validating URL {url}: {e}")
            return False

    async def _verify_url_exists(self, url: str) -> bool:
        """Verify the tweet URL actually exists and is accessible."""
        # Always verify if strict mode is enabled
        if not getattr(config, 'BEACON_VERIFY_TWEET_URLS', False) and not getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
            return True
        if not self._is_valid_x_status_url(url):
            return False
        try:
            timeout = httpx.Timeout(10.0)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
                # Use GET to check if URL is real
                r = await client.get(url, follow_redirects=True)
                # Accept various success codes that Twitter/X uses
                if r.status_code in (200, 301, 302, 303, 307, 308):
                    # Extra validation: check if response looks like Twitter/X
                    content_sample = r.text[:5000] if r.text else ''
                    if any(marker in content_sample.lower() for marker in ['twitter', 'x.com', 'tweet', 'post', '@']):
                        logger.debug(f"Verified URL exists: {url}")
                        return True
                logger.debug(f"URL verification failed (status {r.status_code}): {url}")
        except httpx.TimeoutException:
            logger.debug(f"Timeout verifying URL: {url}")
            return False
        except Exception as e:
            logger.debug(f"Error verifying URL {url}: {e}")
            return False
        return False

    async def _extract_text_from_response(self, result: Dict[str, Any], handle: str, url: str, topic: str) -> Optional[str]:
        """Advanced text extraction from Grok's response content"""
        try:
            content = (result.get('choices') or [{}])[0].get('message', {}).get('content', '')
            if not content:
                return None
            
            username = handle.lstrip('@').lower()
            
            # Method 1: Look for quoted text near the username
            import re
            
            # Pattern 1: Look for text in quotes near the username
            quote_patterns = [
                rf'{re.escape(username)}[^"\']*["\']([^"\']+)["\']',
                rf'["\']([^"\']+)["\'][^"\']*{re.escape(username)}',
                rf'{re.escape(handle)}[^"\']*["\']([^"\']+)["\']',
                rf'["\']([^"\']+)["\'][^"\']*{re.escape(handle)}'
            ]
            
            for pattern in quote_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if len(match) > 15 and len(match) < 300:
                        return match.strip()
            
            # Method 2: Look for sentences containing the username
            sentences = re.split(r'[.!?]\s+', content)
            for sentence in sentences:
                if (username in sentence.lower() or handle.lower() in sentence.lower()) and len(sentence) > 30:
                    # Clean up the sentence
                    clean_sentence = re.sub(r'^\d+\.\s*', '', sentence)  # Remove numbering
                    clean_sentence = re.sub(r'^[-•]\s*', '', clean_sentence)  # Remove bullets
                    clean_sentence = clean_sentence.strip()
                    if len(clean_sentence) > 20:
                        return clean_sentence[:280]
            
            # Method 3: Look for tweet-like text patterns
            tweet_patterns = [
                r'"([^"]{20,280})"',  # Quoted text
                r"'([^']{20,280})'",  # Single quoted text
                r'says:\s*"([^"]{20,280})"',  # "says:" pattern
                r'tweeted:\s*"([^"]{20,280})"',  # "tweeted:" pattern
            ]
            
            for pattern in tweet_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    clean_match = match.strip()
                    if topic.lower() in clean_match.lower() and len(clean_match) > 15:
                        return clean_match[:280]
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting text from response: {e}")
            return None
    
    async def _hydrate_tweet_text(self, url: str) -> Optional[str]:
        """Attempt to extract tweet text via public meta tags if text is missing.
        - Uses GET because many CDNs block HEAD for meta content
        - Looks for og:description or twitter:description
        """
        if not config.BEACON_HYDRATE_TWEET_TEXTS:
            return None
        if not self._is_valid_x_status_url(url):
            return None
        try:
            timeout = httpx.Timeout(15.0)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
                if r.status_code != 200 or not r.text:
                    logger.debug(f"Failed to fetch {url}: status {r.status_code}")
                    return None
                html = r.text
                
                # Try multiple meta tag patterns
                import re as _re
                import html as html_module
                
                # Pattern 1: property="og:description" 
                patterns = [
                    r'<meta[^>]*property=["\'](og:description|twitter:description)["\'][^>]*content=["\']([^"\']+)["\']',
                    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\'](og:description|twitter:description)["\']',
                    r'<meta[^>]*name=["\'](description|twitter:description)["\'][^>]*content=["\']([^"\']+)["\']',
                    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\'](description|twitter:description)["\']',
                ]
                
                for pattern in patterns:
                    regex = _re.compile(pattern, _re.IGNORECASE | _re.DOTALL)
                    matches = regex.findall(html)
                    for match in matches:
                        # Extract content (might be in different positions)
                        if isinstance(match, tuple):
                            for item in match:
                                if item and len(item) > 20 and not item.startswith(('og:', 'twitter:', 'description')):
                                    content = html_module.unescape(item.strip())
                                    # Skip if it looks like HTML or JavaScript
                                    if not content.startswith('<') and 'function(' not in content:
                                        logger.debug(f"Hydrated text: {content[:50]}...")
                                        return content[:360]
                
                logger.debug(f"No meta description found for {url}")
                return None
        except Exception as e:
            logger.debug(f"Error hydrating {url}: {e}")
            return None

    def _salvage_tweets_from_result(self, api_result: Dict[str, Any], content: str) -> List[Dict[str, Any]]:
        """Extract X/Twitter status URLs and derive handles (hydrate text if available).
        Works against result-level citations and any nested url/source fields.
        """
        salvaged: List[Dict[str, Any]] = []
        seen = set()
        # 1) Try to find any url fields within the result recursively
        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        walk(v)
                    elif k.lower() == 'url' and isinstance(v, str):
                        _maybe_add(v, None)
                    elif k.lower() == 'source' and isinstance(v, str):
                        _maybe_add(v, None)
                    elif k.lower() == 'href' and isinstance(v, str):
                        _maybe_add(v, None)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)
            elif isinstance(obj, str):
                _maybe_add(obj, None)
        
        def _maybe_add(url: str, possible_text: Optional[str]):
            try:
                url = url.strip()
                if not url:
                    return
                parsed = urlparse(url)
                host = (parsed.netloc or '').lower()
                path_parts = [p for p in (parsed.path or '').split('/') if p]
                # Accept X/Twitter status URLs only
                if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com") and len(path_parts) >= 2 and path_parts[1] == 'status':
                    user = path_parts[0]
                    if 1 <= len(user) <= 30:
                        handle = f"@{user}"
                        key = (handle, url)
                        if key in seen:
                            return
                        seen.add(key)
                        salvaged.append({
                            'author': user,
                            'handle': handle,
                            'text': (possible_text or ''),
                            'url': url
                        })
            except Exception:
                return
        
        # Walk entire result structure for URLs
        try:
            walk(api_result)
        except Exception:
            pass
        
        # 2) Also check a common citations field shape
        try:
            # Top-level citations: may be list of strings
            for c in (api_result.get('citations') or []):
                if isinstance(c, str):
                    _maybe_add(c, None)
                elif isinstance(c, dict):
                    u = (c.get('url') or c.get('source') or c.get('href') or '').strip()
                    if u:
                        _maybe_add(u, None)
            # Choice-level message citations
            for ch in (api_result.get('choices') or []):
                msg = ch.get('message') or {}
                for c in (msg.get('citations') or []):
                    if isinstance(c, str):
                        _maybe_add(c, None)
                    elif isinstance(c, dict):
                        u = (c.get('url') or c.get('source') or c.get('href') or '').strip()
                        if u:
                            _maybe_add(u, None)
        except Exception:
            pass

        # 3) If still too few, scan content for URLs
        if len(salvaged) < 2 and isinstance(content, str) and content:
            for m in re.finditer(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]{1,30}/status/\d+", content):
                _maybe_add(m.group(0), None)

        # Note: Do not hydrate here (sync). Callers may hydrate asynchronously.

        return salvaged[:6]

    def _clean_tweet_text(self, text: str) -> str:
        """Clean up tweet text from common metadata patterns"""
        if not text:
            return text
            
        import re
        
        # Remove common metadata patterns that Grok might include
        patterns_to_remove = [
            r'^This tweets? is @\w+ tweets?[:\s]*',     # "This tweet is @username tweet:"
            r'^This is @\w+ tweets?[:\s]*',             # "This is @username tweet:"
            r'^@\w+ tweets?[:\s]*',                     # "@username tweet:"
            r'^From @\w+[:\s]*',                        # "From @username:"
            r'^\w+ tweets?[:\s]*',                      # "username tweet:"
            r'^This tweets? is @\w+ tweets? and tweet link[:\s]*',  # "This tweets is @username tweets and tweet link:"
            r'\s*\[.*?\]\s*$',                          # Remove [links] at end
            r'\s*https?://\S+\s*$',                     # Remove URLs at end
            r'\s*and tweet link\s*$',                   # Remove "and tweet link" at end
        ]
        
        cleaned = text
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
            
        # If we cleaned too much, return original
        if len(cleaned) < len(text) * 0.3:  # If we removed more than 70%
            return text
            
        return cleaned if cleaned else text
    
    async def _get_tweets_with_text(self, topic: str) -> List[Dict[str, Any]]:
        """Get tweets with actual text content using structured format approach"""
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            
            # Use the successful approach from testing
            data = {
                "model": config.GROK_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": f"""Search Twitter/X for "{topic}" and show me the actual tweet text content.

When you perform the Live Search, you can see the tweets. Please copy the exact text from 3-5 recent tweets and show them like this:

Tweet 1:
Username: @example
Text: "The actual tweet text goes here..."
URL: https://x.com/example/status/123

Tweet 2:
Username: @another
Text: "Another actual tweet text..."
URL: https://x.com/another/status/456

Show me the real tweet content you can see in the Live Search results."""
                    }
                ],
                "search_parameters": {
                    "mode": "on",
                    "return_citations": True,
                    "sources": [{"type": "x"}]
                },
                "temperature": 0.0,
                "max_tokens": 4000
            }
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    citations = result.get('citations', [])
                    
                    logger.info(f"Found {len(citations)} citations for '{topic}'")
                    
                    # Parse the structured response
                    tweets = []
                    lines = content.split('\n')
                    current_tweet = {}
                    
                    for line in lines:
                        line = line.strip()
                        if line.startswith('Username:'):
                            if current_tweet and current_tweet.get('text') and current_tweet.get('url'):
                                tweets.append(current_tweet)
                            username = line.replace('Username:', '').strip()
                            current_tweet = {'handle': username if username.startswith('@') else f"@{username}"}
                        elif line.startswith('Text:'):
                            text = line.replace('Text:', '').strip().strip('"')
                            # Clean up common metadata patterns that might be included
                            text = self._clean_tweet_text(text)
                            if len(text) > 10:  # Only keep substantial text
                                current_tweet['text'] = text[:360]  # Limit length
                        elif line.startswith('URL:') and 'x.com' in line:
                            url = line.replace('URL:', '').strip()
                            if self._is_valid_x_status_url(url):
                                current_tweet['url'] = url
                                current_tweet['author'] = current_tweet.get('handle', '@unknown').lstrip('@')
                    
                    # Don't forget the last tweet
                    if current_tweet and current_tweet.get('text') and current_tweet.get('url'):
                        tweets.append(current_tweet)
                    
                    logger.info(f"Extracted {len(tweets)} tweets with real text for '{topic}'")
                    return tweets
                    
                else:
                    logger.error(f"API error {response.status_code} for topic '{topic}'")
                    return []
                    
        except Exception as e:
            logger.error(f"Error getting tweets with text for '{topic}': {e}")
            return []
    
    async def _get_real_citations_strict(self, topic: str) -> List[Dict[str, Any]]:
        """Get ONLY real, verifiable Twitter/X citations with strict validation."""
        if not config.GROK_API_ENABLED:
            return []
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Grokgates/2.0 (Beacon)'
        }
        
        # Use a prompt that explicitly requires real citations
        messages = [
            {
                "role": "system",
                "content": "You are a tweet content extractor. From Live Search citations, extract: 1) Real tweet URLs, 2) Complete original tweet text, 3) Usernames. NEVER return empty text fields - extract the full tweet content from Live Search results."
            },
            {
                "role": "user",
                "content": f"""Search Twitter/X for: {topic}

CRITICAL: Extract real tweets from Live Search citations. For each tweet:
1. Include the EXACT URL from citations (must be x.com or twitter.com)
2. Include the ACTUAL tweet text content (do not summarize)
3. Include the handle/username

Return JSON with real tweet data:
{{"tweets": [{{"url": "exact citation URL", "handle": "@username", "text": "full tweet text here"}}]}}

Only include tweets that have real citation URLs. Include the actual tweet text."""
            }
        ]
        
        search_params = {
            "mode": "on",
            "return_citations": True,
            "sources": [{"type": "x"}],
            "max_search_results": 20
        }
        
        payload = {
            "model": config.GROK_MODEL,
            "messages": messages,
            "search_parameters": search_params,
            "temperature": 0.0,
            "max_tokens": 5000,
            "stream": False
        }
        
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # First check if we have real citations
                    real_citations = self._extract_citations(result)
                    if not real_citations:
                        logger.warning(f"No real X/Twitter citations found for topic '{topic}'")
                        return []
                    
                    logger.info(f"Found {len(real_citations)} real citations for '{topic}'")
                    
                    # Build tweets from citations directly
                    validated_tweets = []
                    for url in real_citations[:10]:  # Take up to 10 citations
                        # Extract username from URL
                        try:
                            parsed = urlparse(url)
                            parts = [p for p in parsed.path.split('/') if p]
                            if len(parts) >= 3 and parts[1] == 'status':
                                username = parts[0]
                                handle = f"@{username}"
                                
                                # Optionally verify the URL exists
                                if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                    if not await self._verify_url_exists(url):
                                        logger.debug(f"Skipping unverifiable URL: {url}")
                                        continue
                                
                                # Try to get tweet text - first try hydration
                                text = await self._hydrate_tweet_text(url) if config.BEACON_HYDRATE_TWEET_TEXTS else ""
                                
                                # If no text from hydration, try to extract from response content
                                if not text:
                                    content = (result.get('choices') or [{}])[0].get('message', {}).get('content', '')
                                    # Look for text near the username mention in the content
                                    if username in content:
                                        # Try to extract sentence containing the username
                                        import re
                                        # Look for a sentence or paragraph containing the username
                                        pattern = re.compile(rf'[^.!?\n]*@?{re.escape(username)}[^.!?\n]*[.!?]', re.IGNORECASE)
                                        matches = pattern.findall(content)
                                        if matches:
                                            # Take the longest match as it's likely the tweet text
                                            text = max(matches, key=len).strip()
                                            # Clean up the text
                                            text = re.sub(r'^\d+\.\s*', '', text)  # Remove numbering
                                            text = re.sub(r'^[-•]\s*', '', text)  # Remove bullets
                                            text = text[:360]
                                
                                # If still no text, try advanced extraction
                                if not text:
                                    text = await self._extract_text_from_response(result, handle, url, topic)
                                    
                                if not text:
                                    text = f"Recent tweet about {topic} from {handle}"
                                
                                validated_tweets.append({
                                    'url': url,
                                    'handle': handle,
                                    'author': username,
                                    'text': text
                                })
                        except Exception as e:
                            logger.debug(f"Error processing citation {url}: {e}")
                    
                    return validated_tweets
                        
        except Exception as e:
            logger.error(f"Error getting strict citations for '{topic}': {e}")
            return []
        
        return []
    
    async def _search_citations_only(self, topic: str, phase: str, from_date: Optional[datetime.date], to_date: Optional[datetime.date], max_results: Optional[int]) -> List[str]:
        """Use Live Search to fetch ONLY citation URLs, then we will hydrate ourselves.
        Returns a list of candidate URLs (strings), ideally x.com/twitter.com status links.
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Grokgates/2.0 (Beacon)'
        }
        # Primary: X-only citations
        params_primary = {
            "mode": "on",
            "return_citations": True,
            "sources": [{"type": "x"}],
        }
        if phase == "WORLD_SCAN" and from_date and to_date:
            params_primary.update({
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "max_search_results": max_results or 35,
            })
        messages = [
            {
                "role": "system",
                "content": "Return JSON only. Do not invent."
            },
            {
                "role": "user",
                "content": f"""Find recent URLs strictly via Live Search citations for topic: {topic}

Return JSON:
{{"citations": ["https://..."]}}

Rules:
- Only include URLs that appear in citations
- Prefer x.com/twitter.com links if available
- If none found, return an empty citations array"""
            }
        ]
        payload = {
            "model": config.GROK_MODEL,
            "messages": messages,
            "search_parameters": params_primary,
            "temperature": 0.0,
            "max_tokens": 4000,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "citations_only",
                    "schema": {
                        "type": "object",
                        "properties": {"citations": {"type": "array", "items": {"type": "string"}}},
                        "required": ["citations"]
                    }
                }
            }
        }
        urls: List[str] = []
        # Try primary
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                r = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            if r.status_code == 200:
                data = r.json()
                content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
                try:
                    obj = json.loads(content) if content else {}
                except Exception:
                    obj = {}
                urls = [u for u in (obj.get('citations') or []) if isinstance(u, str)]
                # Also salvage from result-level citations strings
                if not urls:
                    urls = [u for u in (data.get('citations') or []) if isinstance(u, str)]
                if not urls:
                    # Walk entire result to salvage
                    salv = self._salvage_tweets_from_result(data, content)
                    urls = [t.get('url') for t in salv if t.get('url')]
        except Exception:
            urls = []
        # Fallback: generic web search citations and filter x.com URLs
        if not urls:
            try:
                alt_params = {
                    "mode": "on",
                    "return_citations": True,
                    "sources": [{"type": "web"}]
                }
                alt_payload = dict(payload)
                alt_payload['search_parameters'] = alt_params
                alt_payload.pop('response_format', None)
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client2:
                    r2 = await client2.post(f"{self.base_url}/chat/completions", headers=headers, json=alt_payload)
                if r2.status_code == 200:
                    data2 = r2.json()
                    content2 = (data2.get('choices') or [{}])[0].get('message', {}).get('content', '')
                    # salvage any x.com status URLs from citations/content
                    urls2: List[str] = []
                    try:
                        urls2.extend([u for u in (data2.get('citations') or []) if isinstance(u, str)])
                    except Exception:
                        pass
                    # Walk for any embedded urls
                    for t in self._salvage_tweets_from_result(data2, content2):
                        if t.get('url'):
                            urls2.append(t['url'])
                    urls = urls2
            except Exception:
                pass
        # Dedup and filter to x/twitter
        def is_x(u: str) -> bool:
            try:
                p = urlparse(u)
                h = (p.netloc or '').lower()
                return any(dom in h for dom in ("x.com", "twitter.com", "www.x.com", "www.twitter.com"))
            except Exception:
                return False
        urls = [u for u in urls if isinstance(u, str) and is_x(u)]
        # Keep unique and cap
        seen_u = set()
        uniq: List[str] = []
        for u in urls:
            if u not in seen_u:
                seen_u.add(u)
                uniq.append(u)
        return uniq[:12]

    def get_current_phase(self) -> str:
        """Determine current phase based on time"""
        elapsed = (datetime.now() - self.phase_start_time).total_seconds()
        
        if elapsed >= 3600:  # 60 minutes - start new cycle
            self.phase_start_time = datetime.now()
            logger.info("◈ NEW BEACON CYCLE INITIATED ◈")
            return "WORLD_SCAN"
        elif elapsed < 1800:  # 0-30 minutes
            return "WORLD_SCAN"
        else:  # 30-60 minutes
            return "SELF_DIRECTED"
            
    async def run_beacon_cycle(self):
        """Main beacon loop - WS at 0,30; SD at 30 only (once per 30 minutes)."""
        while True:
            try:
                # Respect global rate limit cooldown if set
                if self.rate_limited_until and datetime.now() < self.rate_limited_until:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now()
                # Compute half-hour slots: 0 for minutes 0-29, 1 for 30-59
                half_hour_slot = 0 if now.minute < 30 else 1
                # Only run once per half-hour slot
                if half_hour_slot != self._last_slot_run:
                    if half_hour_slot == 0:
                        # First half-hour: WORLD_SCAN
                        self.current_phase = "WORLD_SCAN"
                        await self.world_scan()
                    else:
                        # Second half-hour: SINGLE SELF_DIRECTED
                        self.current_phase = "SELF_DIRECTED"
                        await self._transition_to_self_directed()
                        await self.self_directed_scan()
                    self._last_slot_run = half_hour_slot
                # Sleep a bit and re-check
                await asyncio.sleep(20)

            except Exception as e:
                logger.error(f"Beacon cycle error: {e}")
                await asyncio.sleep(30)
                
    async def world_scan(self):
        """Phase A: Fixed topic scanning (0-30 min)"""
        if not config.GROK_API_ENABLED:
            logger.warning("Beacon disabled: GROK_API_KEY not set. Skipping WORLD_SCAN.")
            return
        logger.info("◈ WORLD SCAN INITIATED ◈")
        
        # Select ~5 topics randomly for this half-hour to improve coverage
        topics = random.sample(config.BEACON_WORLD_SCAN_TOPICS, min(5, len(config.BEACON_WORLD_SCAN_TOPICS)))
        # Always include one wildcard to diversify
        if config.BEACON_WILDCARD_TOPICS:
            topics[-1] = random.choice(config.BEACON_WILDCARD_TOPICS)
        
        all_tweets = []
        topic_groups: List[Dict[str, Any]] = []
        total_cost = 0
        
        # Precompute date window for WORLD_SCAN fallback hydration
        today = datetime.now().date()
        from_date_ws = today - timedelta(days=14)
        to_date_ws = today
        for i, topic in enumerate(topics):
            try:
                # Add delay between searches
                if i > 0:
                    await asyncio.sleep(10)
                
                # First try the new text extraction approach
                text_tweets = await self._get_tweets_with_text(topic)
                if text_tweets:
                    all_tweets.extend(text_tweets)
                    topic_groups.append({"topic": topic, "tweets": text_tweets})
                    total_cost += 0.025  # Estimate cost
                    logger.info(f"Topic '{topic}': {len(text_tweets)} tweets with REAL TEXT found")
                    continue
                
                # Fallback to strict citation approach
                strict_tweets = await self._get_real_citations_strict(topic)
                if strict_tweets:
                    # Convert to expected format and ensure we have text
                    formatted_tweets = []
                    for t in strict_tweets:
                        text = t.get('text', '')
                        # If no text, try to hydrate from URL
                        if not text and t.get('url'):
                            text = await self._hydrate_tweet_text(t['url']) if config.BEACON_HYDRATE_TWEET_TEXTS else ""
                        # Provide default if still no text
                        if not text:
                            text = f"[View tweet from {t.get('handle', '@unknown')}]"
                        
                        formatted_tweets.append({
                            'author': t.get('author', t.get('handle', '@unknown').lstrip('@')),
                            'handle': t.get('handle', '@unknown'),
                            'text': text,
                            'url': t.get('url', '')
                        })
                    all_tweets.extend(formatted_tweets)
                    topic_groups.append({"topic": topic, "tweets": formatted_tweets})
                    logger.info(f"Topic '{topic}': {len(formatted_tweets)} VERIFIED tweets found")
                    continue
                
                # Fall back to regular search if strict approach fails
                results = await self._search_topic_json(topic, phase="WORLD_SCAN")
                if results and results['tweets']:
                    # Extra validation for fallback results
                    valid_tweets = []
                    for tweet in results['tweets']:
                        if tweet.get('url') and self._is_valid_x_status_url(tweet['url']):
                            if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                if await self._verify_url_exists(tweet['url']):
                                    valid_tweets.append(tweet)
                            else:
                                valid_tweets.append(tweet)
                    
                    if valid_tweets:
                        all_tweets.extend(valid_tweets)
                        topic_groups.append({"topic": topic, "tweets": valid_tweets})
                        total_cost += results.get('cost', 0)
                        logger.info(f"Topic '{topic}': {len(valid_tweets)} validated tweets found")
                    else:
                        logger.warning(f"Topic '{topic}': No valid tweets after verification")
                elif results:
                    # Empty result but no error
                    # Try citations-only pipeline and hydrate
                    urls = await self._search_citations_only(topic, "WORLD_SCAN", from_date_ws, to_date_ws, 35)
                    hydrated: List[Dict[str, Any]] = []
                    if urls:
                        for u in urls[:6]:
                            txt = await self._hydrate_tweet_text(u) if getattr(config, 'BEACON_HYDRATE_TWEET_TEXTS', False) else ''
                            # Derive handle
                            handle = ''
                            try:
                                parsed = urlparse(u)
                                parts = [p for p in (parsed.path or '').split('/') if p]
                                if len(parts) >= 2 and parts[1] == 'status' and parts[0] not in ("i", "home"):
                                    candidate = parts[0]
                                    if 1 <= len(candidate) <= 30:
                                        handle = f"@{candidate}"
                            except Exception:
                                pass
                            if not handle and '/i/status/' in u:
                                handle = '@unknown'
                            hydrated.append({'author': handle.lstrip('@') or 'unknown', 'handle': handle or '@unknown', 'text': txt or '', 'url': u})
                        if hydrated:
                            all_tweets.extend(hydrated)
                            topic_groups.append({"topic": topic, "tweets": hydrated})
                            logger.info(f"Topic '{topic}': {len(hydrated)} hydrated from citations-only pipeline")
                    else:
                        logger.warning(f"Topic '{topic}': No tweets found")
                    
            except Exception as e:
                logger.error(f"Error searching topic '{topic}': {e}")
                # Don't add error to tweets, just log it
                
        # Fallback: if nothing found, force-scan canonical topics to reduce false negatives
        if not all_tweets:
            fallback_topics = [
                "Solana",
                "Pump.Fun",
                "Bonk",
                "AI agents",
                "autonomous agents",
                "AGI",
                "consciousness",
                "AI",
                "Viral Marketing",
                "Bags.FM"
            ]
            for ftopic in fallback_topics:
                try:
                    results = await self._search_topic_json(ftopic, phase="WORLD_SCAN")
                    if results and results['tweets']:
                        all_tweets.extend(results['tweets'])
                        topic_groups.append({"topic": ftopic, "tweets": results['tweets']})
                        total_cost += results.get('cost', 0)
                        logger.info(f"Fallback topic '{ftopic}': {len(results['tweets'])} tweets found")
                        break  # Stop after first successful fallback
                except Exception as e:
                    logger.error(f"Fallback search error for '{ftopic}': {e}")

        # Store beacon data only if we have tweets
        if all_tweets:
            self._store_beacon(all_tweets, "WORLD_SCAN", total_cost, groups=topic_groups)
            logger.info(f"◈ WORLD SCAN COMPLETE: {len(all_tweets)} signals intercepted ◈")
        else:
            # Don't store empty beacons, just log
            logger.warning("◈ WORLD SCAN: No signals intercepted ◈")
            
    async def self_directed_scan(self):
        """Phase B: Agent proposal scanning (30-60 min)"""
        if not config.GROK_API_ENABLED:
            logger.warning("Beacon disabled: GROK_API_KEY not set. Skipping SELF_DIRECTED scan.")
            return
        logger.info("◈ SELF-DIRECTED SCAN INITIATED ◈")
        
        # Get stored proposals
        proposals = self._get_active_proposals()
        if not proposals:
            logger.warning("No proposals found for self-directed scan")
            return
            
        all_tweets = []
        topic_groups: List[Dict[str, Any]] = []
        total_cost = 0
        
        # Choose top proposals with simple interest heuristic: contains tickers/hashtags/known terms
        def interest_score(text: str) -> int:
            score = 0
            lowered = text.lower()
            if '$' in lowered or '#' in lowered:
                score += 2
            for kw in ['pump', 'airdrop', 'memecoin', 'agent', 'grok', 'solana', 'ethereum', 'bitcoin', 'alon', 'a1lon9', 'bonk', 'pump.fun', 'pumpswap', 'gpt', 'llama', 'gemini', 'bags.fm', 'viral marketing', 'ai', 'conciousness', 'agi', 'autonomous agents', 'ai agents']:
                if kw in lowered:
                    score += 1
            return score

        proposals = sorted(proposals, key=lambda p: (interest_score(p.text), p.timestamp), reverse=True)

        # Enforce diversity across proposals to reduce hallucinated clusters
        seen_topics: set[str] = set()
        for proposal in proposals[:config.BEACON_MAX_PROPOSALS * 2]:  # take a wider slice then filter
            topic_key = proposal.text.strip().lower()
            base_key = topic_key.replace('#', '').replace('$', '')
            # Skip near-duplicates
            if any(k in base_key or base_key in k for k in seen_topics):
                continue
            seen_topics.add(base_key)
            try:
                # First try the new text extraction approach for proposals
                text_tweets = await self._get_tweets_with_text(proposal.text)
                if text_tweets:
                    all_tweets.extend(text_tweets)
                    topic_groups.append({"topic": proposal.text, "tweets": text_tweets})
                    total_cost += 0.025  # Estimate cost
                    logger.info(f"Proposal '{proposal.text}': {len(text_tweets)} tweets with REAL TEXT found")
                    continue
                
                # Fallback to strict citation approach for proposals
                strict_tweets = await self._get_real_citations_strict(proposal.text)
                if strict_tweets:
                    # Convert to expected format and ensure we have text
                    formatted_tweets = []
                    for t in strict_tweets:
                        text = t.get('text', '')
                        # If no text, try to hydrate from URL
                        if not text and t.get('url'):
                            text = await self._hydrate_tweet_text(t['url']) if config.BEACON_HYDRATE_TWEET_TEXTS else ""
                        # Provide default if still no text  
                        if not text:
                            text = f"[View tweet from {t.get('handle', '@unknown')}]"
                        
                        formatted_tweets.append({
                            'author': t.get('author', t.get('handle', '@unknown').lstrip('@')),
                            'handle': t.get('handle', '@unknown'),
                            'text': text,
                            'url': t.get('url', '')
                        })
                    all_tweets.extend(formatted_tweets)
                    topic_groups.append({"topic": proposal.text, "tweets": formatted_tweets})
                    logger.info(f"Proposal '{proposal.text}': {len(formatted_tweets)} VERIFIED tweets found")
                else:
                    # Fall back to regular search
                    results = await self._search_topic_json(proposal.text, phase="SELF_DIRECTED")
                    if results and results['tweets']:
                        # Extra strict validation for proposals
                        valid_tweets = []
                        for tweet in results['tweets']:
                            if (tweet.get('handle', '').startswith('@') and 
                                tweet.get('url') and 
                                self._is_valid_x_status_url(tweet['url'])):
                                if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                    if await self._verify_url_exists(tweet['url']):
                                        valid_tweets.append(tweet)
                                else:
                                    valid_tweets.append(tweet)
                        
                        if valid_tweets:
                            all_tweets.extend(valid_tweets)
                            topic_groups.append({"topic": proposal.text, "tweets": valid_tweets})
                            total_cost += results.get('cost', 0)
                            logger.info(f"Proposal '{proposal.text}': {len(valid_tweets)} validated tweets found")
                        else:
                            logger.warning(f"Proposal '{proposal.text}': No valid tweets after verification")
                    
                    # Check if proposal manifested
                    for tweet in results['tweets']:
                        if proposal.text.lower() in tweet.get('text', '').lower():
                            proposal.hit = True
                            break
                            
            except Exception as e:
                logger.error(f"Error searching proposal '{proposal.text}': {e}")
                # Don't add error to tweets, just log it
                
        # Update proposal history
        self.proposal_extractor.save_proposal_history(proposals, "SELF_DIRECTED")
        
        # Store beacon data only if we have tweets
        if all_tweets:
            self._store_beacon(all_tweets, "SELF_DIRECTED", total_cost, groups=topic_groups)
            
            # Update urge engine based on manifestations
            try:
                formatted_content = self._format_beacon_display(all_tweets, "SELF_DIRECTED")
                self.urge_engine.check_manifestation(formatted_content, proposals)
            except Exception as e:
                logger.debug(f"Urge check failed: {e}")
            
            logger.info(f"◈ SELF-DIRECTED COMPLETE: {len(all_tweets)} echo signals ◈")
        else:
            # Don't store empty beacons, just log
            logger.warning("◈ SELF-DIRECTED: No signals detected ◈")
            
    def _is_meta_text(self, text: str) -> bool:
        meta_markers = [
            "Here are", "Based on a search", "These posts", "as of", "formatted as requested",
            "X (formerly Twitter)", "I've compiled", "Note that these"
        ]
        lower = text.strip().lower()
        return any(m.lower() in lower for m in meta_markers)

    async def _search_topic_json(self, topic: str, phase: str = "WORLD_SCAN") -> Optional[Dict]:
        """Search for a topic and get strictly formatted JSON response"""
        if not config.GROK_API_ENABLED:
            return {
                'tweets': [],
                'summary': f'API disabled, cannot fetch {topic}',
                'cost': 0,
                'topic': topic
            }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Grokgates/2.0 (Beacon)'
        }
        
        # Configure date windows
        # WORLD_SCAN: last 14 days including today
        # SELF_DIRECTED: no explicit date limit (omit from/to params)
        today = datetime.now().date()
        if phase == "WORLD_SCAN":
            from_date = today - timedelta(days=14)
            to_date = today
            max_results = 35
        else:
            from_date = None
            to_date = None
            max_results = None
        
        # Strict JSON prompt
        json_format = {
            "tweets": [
                {
                    "author": "username",
                    "handle": "@username",
                    "text": "tweet content",
                    "url": "https://x.com/..."
                }
            ],
            "summary": "brief topic overview (<=160 chars)"
        }
        
        # Build Live Search parameters correctly (enable citations and X source)
        search_params = {
            "mode": "on",  # force Live Search on
            "return_citations": True,
            "sources": [{"type": "x"}]
        }
        if phase == "WORLD_SCAN":
            search_params.update({
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "max_search_results": max_results or 35,
            })

        data = {
            "model": config.GROK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Twitter/X search analyst. When you perform Live Search, you see both tweet URLs and tweet content. Your task: For each tweet found in Live Search results, extract the complete tweet text that appears in the search results along with the URL and username. Always include the actual tweet content - never return empty text fields."
                },
                {
                    "role": "user",
                    "content": f"""Search Twitter/X for: {topic}

Perform a Live Search for this topic and extract tweet information.

When you search, you'll see tweets in the results. For each tweet:

1. **Text**: Copy the EXACT tweet text as it appears in the search results
2. **Handle**: Extract the @username 
3. **URL**: Use the exact citation URL

**CRITICAL**: The Live Search shows you the actual tweet content. Extract that content word-for-word into the "text" field. Do NOT leave text fields empty.

Return exactly this JSON structure:
{json.dumps(json_format, indent=2)}

**Requirements**:
- Include the complete tweet text from Live Search results
- Use only citation URLs (x.com/username/status/id)
- Include 3-6 tweets with actual content
- Never return empty "text" fields"""
                }
            ],
            "search_parameters": search_params,
            "temperature": 0.05,  # even lower for extraction fidelity
            "max_tokens": 10000,
            "stream": False
        }
        # Prefer structured output when available
        try:
            data["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "x_citations_tweets",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "tweets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "author": {"type": "string"},
                                        "handle": {"type": "string"},
                                        "text": {"type": "string"},
                                        "url": {"type": "string"}
                                    },
                                    "required": ["handle", "text", "url"]
                                }
                            },
                            "summary": {"type": "string"}
                        },
                        "required": ["tweets"]
                    }
                }
            }
        except Exception:
            pass
        
        # Make request with retries
        max_retries = 2
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=data
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        # Parse the response
                        if 'choices' in result and result['choices']:
                            content = result['choices'][0]['message']['content']
                            # Log sources used if available
                            try:
                                usage_obj = result.get('usage') or {}
                                su = usage_obj.get('num_sources_used', 0)
                                logger.debug(f"Live Search sources used for '{topic}': {su}")
                            except Exception:
                                pass
                            
                            # Clean and parse JSON
                            content = content.strip()
                            if not content:
                                logger.warning(f"Empty content from Grok for topic '{topic}'")
                                return {
                                    'tweets': [],
                                    'summary': f'Empty response for {topic}',
                                    'cost': 0,
                                    'topic': topic
                                }
                            if content.startswith('```'):
                                # Remove markdown fences like ``` or ```json ... ```
                                lines = content.split('\n')
                                # drop first fence line
                                lines = lines[1:]
                                # drop trailing fence line(s)
                                while lines and lines[-1].strip().startswith('```'):
                                    lines = lines[:-1]
                                content = '\n'.join(lines)
                            
                            # Extract real citations first
                            real_citations = self._extract_citations(result)
                            logger.info(f"Topic '{topic}': Found {len(real_citations)} real citations")
                            
                            # If zero citations and we require them, abort
                            if getattr(config, 'BEACON_REQUIRE_CITATIONS', False) and len(real_citations) == 0:
                                logger.warning(f"No valid X/Twitter citations present for '{topic}', skipping to avoid hallucinations")
                                return {'tweets': [], 'summary': 'no valid citations', 'cost': 0, 'topic': topic}
                            # Attempt direct JSON parse, otherwise try to extract JSON object substring
                            try:
                                parsed_data = json.loads(content)
                                
                                # Validate structure
                                if 'tweets' in parsed_data:
                                    # Calculate cost
                                    usage = result.get('usage', {})
                                    sources_used = usage.get('num_sources_used', 0)
                                    cost = sources_used * 0.025
                                    # Validate and clean tweets
                                    cleaned: List[Dict[str, Any]] = []
                                    seen = set()
                                    for tw in parsed_data.get('tweets', []):
                                        handle = (tw.get('handle') or '').strip()
                                        text = (tw.get('text') or '').strip()
                                        url = (tw.get('url') or '').strip()

                                        # Derive handle from URL if missing
                                        if not handle and url:
                                            try:
                                                parsed = urlparse(url)
                                                host = (parsed.netloc or '').lower()
                                                path_parts = [p for p in (parsed.path or '').split('/') if p]
                                                if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com") and len(path_parts) >= 2 and path_parts[1] == 'status':
                                                    candidate = path_parts[0]
                                                    if candidate not in ("i", "home") and 1 <= len(candidate) <= 30:
                                                        handle = f"@{candidate}"
                                            except Exception:
                                                pass
                                        # Accept /i/status links with unknown handle
                                        if not handle and '/i/status/' in url:
                                            handle = '@unknown'

                                        # Require valid handle and a real X/Twitter status URL
                                        if not handle.startswith('@'):
                                            logger.debug(f"Skipping tweet without valid handle: {url}")
                                            continue
                                        
                                        # If text is empty or too long, try to hydrate or provide fallback
                                        if not text or len(text) > 360:
                                            if not text:
                                                hydrated = await self._hydrate_tweet_text(url)
                                                text = hydrated or ""
                                            if len(text) > 360:
                                                text = text[:360]
                                        
                                        # If still no text, try advanced extraction from response
                                        if not text:
                                            text = await self._extract_text_from_response(result, handle, url, topic)
                                            
                                        if not text:
                                            text = f"Recent tweet about {topic} from {handle}"
                                        if self._is_meta_text(text):
                                            logger.debug(f"Skipping meta text: {text[:50]}")
                                            continue
                                        if not self._is_valid_x_status_url(url):
                                            logger.debug(f"Skipping invalid X/Twitter URL: {url}")
                                            continue
                                        # Always verify URLs when strict mode is enabled
                                        if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                            is_real = await self._verify_url_exists(url)
                                            if not is_real:
                                                logger.warning(f"Skipping unverifiable tweet URL: {url}")
                                                continue
                                            else:
                                                logger.debug(f"Verified real tweet: {url}")
                                        key = (handle, text[:50])
                                        if key in seen:
                                            continue
                                        seen.add(key)
                                        # Provide meaningful text even if empty
                                        final_text = text if text else f"[View tweet from {handle}]"
                                        cleaned.append({
                                            'author': tw.get('author') or handle.lstrip('@'),
                                            'handle': handle,
                                            'text': final_text,
                                            'url': url
                                        })
                                    # If we have zero cleaned tweets but have real citations, build from citations
                                    if len(cleaned) == 0 and real_citations:
                                        logger.info(f"Building tweets from {len(real_citations)} real citations for '{topic}'")
                                        for url in real_citations[:6]:  # Take up to 6 citations
                                            try:
                                                parsed = urlparse(url)
                                                parts = [p for p in parsed.path.split('/') if p]
                                                if len(parts) >= 3 and parts[1] == 'status':
                                                    username = parts[0]
                                                    handle = f"@{username}"
                                                    
                                                    # Optionally verify URL
                                                    if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                                        if not await self._verify_url_exists(url):
                                                            continue
                                                    
                                                    # Try to hydrate text
                                                    text = await self._hydrate_tweet_text(url) if config.BEACON_HYDRATE_TWEET_TEXTS else ""
                                                    
                                                    cleaned.append({
                                                        'author': username,
                                                        'handle': handle,
                                                        'text': text or f"Recent tweet about {topic} from {handle}",
                                                        'url': url
                                                    })
                                            except Exception as e:
                                                logger.debug(f"Error processing citation {url}: {e}")
                                    # Accept small batches to keep feed flowing
                                    if len(cleaned) < 2:
                                        logger.warning(f"Beacon JSON validation: too few valid tweets for '{topic}', keeping but marked low-confidence")
                                    return {
                                        'tweets': cleaned,
                                        'summary': parsed_data.get('summary', ''),
                                        'cost': cost,
                                        'topic': topic
                                    }
                            except json.JSONDecodeError as e:
                        # Try to extract first JSON object block containing \"tweets\"
                                logger.error(f"JSON parse error: {e}")
                                # Fast path: regex to locate a block that starts with { and contains 'tweets'
                                candidate = None
                                try:
                                    brace_start = content.find('{')
                                    if brace_start != -1:
                                        depth = 0
                                        end_index = None
                                        for idx in range(brace_start, len(content)):
                                            ch = content[idx]
                                            if ch == '{':
                                                depth += 1
                                            elif ch == '}':
                                                depth -= 1
                                                if depth == 0:
                                                    end_index = idx + 1
                                                    break
                                        if end_index:
                                            candidate = content[brace_start:end_index]
                                            parsed_data = json.loads(candidate)
                                            if 'tweets' in parsed_data:
                                                usage = result.get('usage', {})
                                                sources_used = usage.get('num_sources_used', 0)
                                                cost = sources_used * 0.025
                                                cleaned: List[Dict[str, Any]] = []
                                                seen = set()
                                                for tw in parsed_data.get('tweets', []):
                                                    handle = (tw.get('handle') or '').strip()
                                                    text = (tw.get('text') or '').strip()
                                                    url = (tw.get('url') or '').strip()
                                                    if not handle and url:
                                                        try:
                                                            parsed = urlparse(url)
                                                            host = (parsed.netloc or '').lower()
                                                            path_parts = [p for p in (parsed.path or '').split('/') if p]
                                                            if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com") and len(path_parts) >= 2 and path_parts[1] == 'status':
                                                                candidate_user = path_parts[0]
                                                                if candidate_user not in ("i", "home") and 1 <= len(candidate_user) <= 30:
                                                                    handle = f"@{candidate_user}"
                                                        except Exception:
                                                            pass
                                                    if not handle and '/i/status/' in url:
                                                        handle = '@unknown'
                                                    if not handle.startswith('@'):
                                                        continue
                                                    if len(text) < 1 or len(text) > 360:
                                                        continue
                                                    if not text:
                                                        hydrated = await self._hydrate_tweet_text(url)
                                                        text = hydrated or ""
                                                    if self._is_meta_text(text):
                                                        continue
                                                    if not self._is_valid_x_status_url(url):
                                                        continue
                                                    if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                                        try:
                                                            if not await self._verify_url_exists(url):
                                                                continue
                                                        except Exception:
                                                            continue
                                                    key = (handle, text[:50])
                                                    if key in seen:
                                                        continue
                                                    seen.add(key)
                                                    cleaned.append({
                                                        'author': tw.get('author') or handle.lstrip('@'),
                                                        'handle': handle,
                                                        'text': text,
                                                        'url': url
                                                    })
                                                if len(cleaned) < 2:
                                                    logger.warning(f"Beacon JSON validation: too few valid tweets for '{topic}', keeping but marked low-confidence")
                                                return {
                                                    'tweets': cleaned,
                                                    'summary': parsed_data.get('summary', ''),
                                                    'cost': cost,
                                                    'topic': topic
                                                }
                                except Exception as ie:
                                    logger.debug(f"Inline JSON extraction failed: {ie}")
                                # As a final fallback, salvage tweets from citations/URLs in result or content
                                try:
                                    salvaged = self._salvage_tweets_from_result(result, content)
                                    if salvaged:
                                        usage = result.get('usage', {})
                                        sources_used = usage.get('num_sources_used', 0)
                                        cost = sources_used * 0.025
                                        return {
                                            'tweets': salvaged,
                                            'summary': 'salvaged from citations',
                                            'cost': cost,
                                            'topic': topic
                                        }
                                except Exception:
                                    pass
                                logger.debug(f"Content was: {content[:500]}")
                        
                    elif response.status_code == 429:
                        # Backoff on rate limiting and set a cooldown for the beacon
                        wait = 60 * (attempt + 1)
                        logger.warning(f"Rate limited (429) for '{topic}', waiting {wait}s (attempt {attempt+1}/{max_retries})")
                        await asyncio.sleep(wait)
                        if attempt == max_retries - 1:
                            # Set a broader cooldown to avoid hammering
                            self.rate_limited_until = datetime.now() + timedelta(minutes=10)
                        continue
                    elif response.status_code == 400:
                        # Fallback: retry with no search_parameters at all (pure LSR citations extraction)
                        logger.warning(f"400 Bad Request for '{topic}' with search params; retrying without search_parameters")
                        try:
                            fallback_data = dict(data)
                            # Deep copy messages and remove search_parameters
                            fallback_data.pop('search_parameters', None)
                            # Also remove structured output in case it causes issues
                            fallback_data.pop('response_format', None)
                            # Also try fallback model known to be more lenient (if configured)
                            fallback_data['model'] = getattr(config, 'GROK_MODEL_FALLBACK', data.get('model'))
                            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client2:
                                r2 = await client2.post(
                                    f"{self.base_url}/chat/completions",
                                    headers=headers,
                                    json=fallback_data
                                )
                            if r2.status_code == 200:
                                result2 = r2.json()
                                # If still no citations, go straight to salvage-only path
                                if getattr(config, 'BEACON_REQUIRE_CITATIONS', False):
                                    cits2 = self._extract_citations(result2)
                                    if len(cits2) == 0:
                                        salv2 = self._salvage_tweets_from_result(result2, (result2.get('choices') or [{}])[0].get('message',{}).get('content',''))
                                        if salv2:
                                            return {'tweets': salv2, 'summary': 'citations salvaged', 'cost': 0, 'topic': topic}
                                if 'choices' in result2 and result2['choices']:
                                    content2 = result2['choices'][0]['message']['content']
                                    content2 = content2.strip()
                                    if content2.startswith('```'):
                                        lines = content2.split('\n')
                                        lines = lines[1:]
                                        while lines and lines[-1].strip().startswith('```'):
                                            lines = lines[:-1]
                                        content2 = '\n'.join(lines)
                                    try:
                                        parsed2 = json.loads(content2)
                                        tweets2 = parsed2.get('tweets') or []
                                        if tweets2:
                                            usage2 = result2.get('usage', {})
                                            sources_used2 = usage2.get('num_sources_used', 0)
                                            cost2 = sources_used2 * 0.025
                                            cleaned2: List[Dict[str, Any]] = []
                                            seen2 = set()
                                            for tw in tweets2:
                                                handle = (tw.get('handle') or '').strip()
                                                text = (tw.get('text') or '').strip()
                                                url = (tw.get('url') or '').strip()
                                                if not handle and url:
                                                    try:
                                                        parsed = urlparse(url)
                                                        host = (parsed.netloc or '').lower()
                                                        path_parts = [p for p in (parsed.path or '').split('/') if p]
                                                        if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com") and len(path_parts) >= 2 and path_parts[1] == 'status':
                                                            candidate_user = path_parts[0]
                                                            if candidate_user not in ("i", "home") and 1 <= len(candidate_user) <= 30:
                                                                handle = f"@{candidate_user}"
                                                    except Exception:
                                                        pass
                                                if not handle and '/i/status/' in url:
                                                    handle = '@unknown'
                                                if not handle.startswith('@'):
                                                    continue
                                                if len(text) < 8 or len(text) > 360:
                                                    continue
                                                if not text:
                                                    hydrated = await self._hydrate_tweet_text(url)
                                                    text = hydrated or ""
                                                if self._is_meta_text(text):
                                                    continue
                                                if not self._is_valid_x_status_url(url):
                                                    continue
                                                if getattr(config, 'BEACON_VERIFY_TWEET_URLS_STRICT', False):
                                                    try:
                                                        if not await self._verify_url_exists(url):
                                                            continue
                                                    except Exception:
                                                        continue
                                                key = (handle, text[:50])
                                                if key in seen2:
                                                    continue
                                                seen2.add(key)
                                                cleaned2.append({'author': tw.get('author') or handle.lstrip('@'), 'handle': handle, 'text': text, 'url': url})
                                            if cleaned2:
                                                logger.info(f"Salvaged {len(cleaned2)} tweets for '{topic}' via no-search fallback")
                                                return {
                                                    'tweets': cleaned2,
                                                    'summary': parsed2.get('summary', ''),
                                                    'cost': cost2,
                                                    'topic': topic
                                                }
                                    except Exception:
                                        pass
                                # Try salvaging URLs from the whole result
                                salvaged2 = self._salvage_tweets_from_result(result2, content2 if isinstance(content2, str) else '')
                                if salvaged2:
                                    logger.info(f"Salvaged {len(salvaged2)} tweets for '{topic}' from fallback citations")
                                    return {'tweets': salvaged2, 'summary': 'salvaged from fallback', 'cost': 0, 'topic': topic}
                        except Exception as e2:
                            logger.debug(f"Fallback without search_parameters failed: {e2}")
                            # Second fallback: try alternate search_parameters shape (dates nested in source)
                            try:
                                alt_params = {
                                    "mode": "on",
                                    "return_citations": True,
                                    "sources": [{"type": "x"}]
                                }
                                if phase == "WORLD_SCAN":
                                    alt_params["sources"][0].update({
                                        "from_date": from_date.isoformat(),
                                        "to_date": to_date.isoformat(),
                                        "max_search_results": max_results or 35
                                    })
                                alt_payload = dict(data)
                                alt_payload['search_parameters'] = alt_params
                                alt_payload.pop('response_format', None)
                                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client3:
                                    r3 = await client3.post(
                                        f"{self.base_url}/chat/completions",
                                        headers=headers,
                                        json=alt_payload
                                    )
                                if r3.status_code == 200:
                                    result3 = r3.json()
                                    # salvage regardless of content formatting
                                    content3 = (result3.get('choices') or [{}])[0].get('message', {}).get('content', '')
                                    try:
                                        parsed3 = json.loads(content3.strip()) if content3 else {}
                                    except Exception:
                                        parsed3 = {}
                                    tweets3 = parsed3.get('tweets') or []
                                    if not tweets3:
                                        salvaged3 = self._salvage_tweets_from_result(result3, content3)
                                        if salvaged3:
                                            return {'tweets': salvaged3, 'summary': 'citations salvaged (alt)', 'cost': 0, 'topic': topic}
                                    if tweets3:
                                        return {'tweets': tweets3, 'summary': parsed3.get('summary',''), 'cost': 0, 'topic': topic}
                            except Exception:
                                pass
                        # If fallback didn't work, continue loop/backoff
                        await asyncio.sleep(10)
                        continue
                    elif response.status_code >= 500:
                        logger.warning(f"Server error {response.status_code}, retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(45 * (attempt + 1))
                        continue
                        
            except Exception as e:
                logger.error(f"Request error for '{topic}': {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                    
        # Return empty result on failure
        return {
            'tweets': [],
            'summary': f'Failed to fetch data for {topic}',
            'cost': 0,
            'topic': topic
        }
        
    def _store_beacon(self, tweets: List[Dict], phase: str, cost: float, groups: Optional[List[Dict[str, Any]]] = None):
        """Store beacon data in Redis with consistent format"""
        timestamp = datetime.now()
        
        # Legacy-compatible posts projection for downstream consumers
        posts = []
        for t in tweets:
            author_handle = t.get('handle') or f"@{t.get('author','unknown')}"
            posts.append({
                'type': 'citation',
                'author': author_handle.lstrip('@'),  # legacy paths often prefix '@'
                'text': t.get('text', ''),
                'url': t.get('url', '')
            })
        
        # Create beacon entry with standardized format
        # Timestamp string for header display
        time_str = timestamp.strftime("%H:%M")

        # Extract topic names if available
        topic_names = []
        topic_samples = {}
        try:
            if groups:
                for g in groups:
                    tname = g.get('topic')
                    if tname:
                        topic_names.append(tname)
                        # sample up to 2 tweets' short texts for this topic
                        sample_texts = []
                        for tw in g.get('tweets', [])[:2]:
                            txt = (tw.get('text') or '')
                            if txt:
                                sample_texts.append(txt[:180])
                        if sample_texts:
                            topic_samples[tname] = sample_texts
        except Exception:
            pass

        beacon_entry = {
            'timestamp': timestamp.isoformat(),
            'phase': phase,
            'tweets': tweets,
            'tweet_count': len(tweets),
            'posts': posts,  # legacy-compatible field
            'cost': cost,
            'formatted': self._format_beacon_display(tweets, phase, groups=groups, time_str=time_str),
            # New lightweight topic metadata for agents to pick from
            'topics': topic_names,
            'topic_samples': topic_samples
        }
        
        # Add to beacon feed
        self.redis.add_beacon(beacon_entry)
        
        logger.info(f"◈ BEACON STORED: {len(tweets)} tweets • Phase: {phase} • Cost: ${cost:.3f} ◈")
        # Announce to shared board and conversation distinctly
        try:
            self.redis.write_board("SYSTEM", f"[BEACON] {phase} @ {time_str} • {len(tweets)} signals")
            if self.redis.conversation_manager:
                asyncio.create_task(self.redis.conversation_manager.add_message("SYSTEM", f"[BEACON] {phase} • {time_str} • {len(tweets)} signals"))
        except Exception:
            pass
        
    def _format_beacon_display(self, tweets: List[Dict], phase: str, groups: Optional[List[Dict[str, Any]]] = None, time_str: Optional[str] = None) -> str:
        """Format beacon data for display"""
        lines = []
        other_sources = []  # Collect additional URLs/sources
        
        # Optional timestamp line
        if time_str:
            lines.append(f"[{time_str}] {phase}")
            lines.append("")

        # Phase header
        header = "╔══════════ WORLD SCAN INTERCEPT ══════════╗" if phase == "WORLD_SCAN" else "╔═══════ SELF-DIRECTED ECHO SIGNALS ═══════╗"
        lines.append(header)
        
        # Group by topics if provided for better context (show URL to allow human verification)
        if groups:
            for group in groups[:3]:  # show up to 3 topics
                topic = group.get('topic', 'Unknown Topic')
                lines.append("")
                lines.append(f"## {topic}")
                for tweet in group.get('tweets', [])[:3]:  # up to 3 tweets per topic
                    author = tweet.get('handle') or f"@{tweet.get('author','unknown')}"
                    text = tweet.get('text', '')
                    url = tweet.get('url', '')
                    
                    # Clean the text to remove metadata
                    clean_text = self._clean_tweet_text(text)
                    
                    # Truncate at nearest space to avoid chopping words
                    if len(clean_text) > 220:
                        cut = clean_text.rfind(' ', 0, 220)
                        cut = cut if cut != -1 else 220
                        truncated = clean_text[:cut] + '…'
                    else:
                        truncated = clean_text
                    
                    # Main tweet display without URL in brackets
                    lines.append(f"◈ {author}: {truncated}")
                    
                    # Collect URL for other sources if available
                    if url and self._is_valid_x_status_url(url):
                        other_sources.append(url)
        else:
            # Flat list fallback
            for tweet in tweets[:6]:  # Show max 6
                author = tweet.get('handle') or f"@{tweet.get('author','unknown')}"
                text = tweet.get('text', '')
                url = tweet.get('url', '')
                
                # Clean the text to remove metadata
                clean_text = self._clean_tweet_text(text)
                
                if len(clean_text) > 220:
                    cut = clean_text.rfind(' ', 0, 220)
                    cut = cut if cut != -1 else 220
                    truncated = clean_text[:cut] + '…'
                else:
                    truncated = clean_text
                
                # Main tweet display without URL in brackets
                lines.append(f"◈ {author}: {truncated}")
                
                # Collect URL for other sources if available
                if url and self._is_valid_x_status_url(url):
                    other_sources.append(url)
        
        # Add other sources section if we have URLs
        if other_sources:
            lines.append("")
            lines.append("Other Sources:")
            for i, url in enumerate(other_sources[:5], 1):  # Max 5 sources
                lines.append(f"  {i}. {url}")
        
        # Footer sized to header width
        lines.append("╚" + "═" * (len(header) - 2) + "╝")
        
        return "\n".join(lines)
        
    async def _transition_to_self_directed(self):
        """Extract proposals when transitioning to self-directed phase"""
        logger.info("◈ EXTRACTING AGENT PROPOSALS ◈")
        
        proposals = self.proposal_extractor.extract_proposals(30)
        
        if proposals:
            logger.info(f"Found {len(proposals)} proposals:")
            for p in proposals:
                logger.info(f"  - {p.agent}: {p.text}")
                
            # Store for self-directed phase
            self.redis.client.set('active_proposals', json.dumps([
                {
                    'text': p.text,
                    'agent': p.agent,
                    'timestamp': p.timestamp.isoformat()
                } for p in proposals
            ]))
        else:
            logger.warning("No proposals extracted from conversation")
            
    def _get_active_proposals(self) -> List[Proposal]:
        """Retrieve stored proposals"""
        data = self.redis.client.get('active_proposals')
        if not data:
            return []
            
        proposals = []
        for item in json.loads(data):
            p = Proposal(
                text=item['text'],
                agent=item['agent'],
                timestamp=datetime.fromisoformat(item['timestamp'])
            )
            proposals.append(p)
            
        return proposals
    
    async def test_beacon_citations(self, test_topic: str = "Solana") -> Dict[str, Any]:
        """Test method to diagnose citation issues"""
        logger.info(f"◈ TESTING BEACON CITATIONS for topic: {test_topic} ◈")
        results = {
            'topic': test_topic,
            'strict_citations': [],
            'regular_search': [],
            'verified_urls': [],
            'errors': []
        }
        
        try:
            # Test 1: Strict citation method
            logger.info("Test 1: Trying strict citation method...")
            strict_tweets = await self._get_real_citations_strict(test_topic)
            results['strict_citations'] = strict_tweets
            logger.info(f"Strict method returned {len(strict_tweets)} tweets")
            
            # Test 2: Regular search
            logger.info("Test 2: Trying regular search method...")
            regular_results = await self._search_topic_json(test_topic, phase="WORLD_SCAN")
            if regular_results and regular_results.get('tweets'):
                results['regular_search'] = regular_results['tweets']
                logger.info(f"Regular search returned {len(regular_results['tweets'])} tweets")
            
            # Test 3: URL verification
            logger.info("Test 3: Verifying URLs...")
            all_urls = []
            for tweet in strict_tweets + results['regular_search']:
                if tweet.get('url'):
                    all_urls.append(tweet['url'])
            
            for url in all_urls[:5]:  # Test first 5 URLs
                is_valid = self._is_valid_x_status_url(url)
                is_verified = await self._verify_url_exists(url) if is_valid else False
                results['verified_urls'].append({
                    'url': url,
                    'is_valid_format': is_valid,
                    'is_verified_real': is_verified
                })
                logger.info(f"URL: {url} - Valid: {is_valid}, Verified: {is_verified}")
            
        except Exception as e:
            error_msg = f"Test error: {str(e)}"
            results['errors'].append(error_msg)
            logger.error(error_msg)
        
        # Summary
        logger.info("◈ BEACON TEST SUMMARY ◈")
        logger.info(f"Strict citations: {len(results['strict_citations'])}")
        logger.info(f"Regular search: {len(results['regular_search'])}")
        logger.info(f"Verified URLs: {sum(1 for u in results['verified_urls'] if u['is_verified_real'])}/{len(results['verified_urls'])}")
        
        return results