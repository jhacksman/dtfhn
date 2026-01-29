"""
Hybrid article scraper with newspaper3k (fast) and Playwright (JS fallback).

Usage:
    text, status = fetch_article_text(url)
    # status: "full" (newspaper3k), "full_js" (playwright), "full_archive" (wayback),
    #         "full_alt" (alternative URL), "title_only" (all failed)
"""

import re
import time
from typing import Tuple, Optional
from urllib.parse import urlparse

import requests
from newspaper import Article


# Domains to skip when extracting alternative URLs from HN comments
BLOCKED_ALT_DOMAINS = {
    "archive.ph", "archive.is", "12ft.io", "twitter.com", "x.com"
}


# JS warning patterns - common messages when content requires JavaScript
JS_WARNING_PATTERNS = [
    r"enable javascript",
    r"javascript is required",
    r"javascript is disabled",
    r"please enable javascript",
    r"this site requires javascript",
    r"you need to enable javascript",
    r"browser doesn't support javascript",
    r"javascript must be enabled",
    r"turn on javascript",
    r"activate javascript",
    r"requires a javascript",
    r"we've detected that javascript",
]


def looks_like_js_warning(text: str) -> bool:
    """
    Detect if extracted text is just a JavaScript requirement warning.
    
    Returns True if the text appears to be a JS warning message rather than
    actual article content.
    """
    if not text or len(text.strip()) < 50:
        return True  # Too short to be real content
    
    text_lower = text.lower()
    
    # Check for JS warning patterns
    for pattern in JS_WARNING_PATTERNS:
        if re.search(pattern, text_lower):
            # Only flag as JS warning if the text is short (< 500 chars)
            # Real articles might mention JavaScript but have lots of other content
            if len(text.strip()) < 500:
                return True
    
    return False


def try_wayback(url: str, timeout: int = 15) -> Tuple[Optional[str], str]:
    """
    Try to fetch article from Wayback Machine archive.
    
    Args:
        url: Original article URL
        timeout: Request timeout in seconds
        
    Returns:
        (text, status) tuple where:
        - text: Extracted article text or None on failure
        - status: "full_archive" if successful, "failed" if not
    """
    try:
        # Check Wayback API for archived version
        api_url = f"https://archive.org/wayback/available?url={url}"
        response = requests.get(api_url, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        snapshots = data.get("archived_snapshots", {})
        closest = snapshots.get("closest", {})
        
        if not closest.get("available"):
            return None, "failed"
        
        archive_url = closest.get("url")
        if not archive_url:
            return None, "failed"
        
        # Fetch from Wayback using newspaper3k
        text, _ = try_newspaper3k(archive_url, timeout=timeout)
        if text and len(text.strip()) > 200:
            return text, "full_archive"
        
        return None, "failed"
        
    except Exception as e:
        return None, "failed"


def extract_alternative_urls(hn_text: str, original_url: str) -> list[str]:
    """
    Extract alternative URLs from HN post text (for when someone posts a mirror).
    
    Args:
        hn_text: Text content from HN post (usually for Show HN / Ask HN)
        original_url: The original article URL (to avoid duplicates)
        
    Returns:
        List of alternative URLs found, excluding blocked domains
    """
    if not hn_text:
        return []
    
    # Decode HTML entities (&#x2F; -> /, etc.)
    import html
    hn_text = html.unescape(hn_text)
    
    # Find all URLs in the text
    url_pattern = r'https?://[^\s<>"\')\]]+(?:\.[^\s<>"\')\]]+)+'
    found_urls = re.findall(url_pattern, hn_text)
    
    # Filter out truncated URLs (ending with ...)
    found_urls = [u for u in found_urls if not u.endswith('...') and not u.endswith('..')]
    
    # Parse original URL for comparison
    try:
        original_domain = urlparse(original_url).netloc.lower()
    except:
        original_domain = ""
    
    alt_urls = []
    for url in found_urls:
        try:
            domain = urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            
            # Skip if it's the same domain as original
            if domain == original_domain or domain == original_domain.replace("www.", ""):
                continue
            
            # Skip blocked domains
            if domain in BLOCKED_ALT_DOMAINS:
                continue
            
            # Skip HN links
            if "ycombinator.com" in domain or "news.ycombinator" in domain:
                continue
            
            alt_urls.append(url)
        except:
            continue
    
    return alt_urls


def try_alternative_urls(hn_text: str, original_url: str) -> Tuple[Optional[str], str]:
    """
    Try to fetch article from alternative URLs found in HN post text.
    
    Args:
        hn_text: Text content from HN post
        original_url: The original article URL
        
    Returns:
        (text, status) tuple where:
        - text: Extracted article text or None on failure
        - status: "full_alt" if successful, "failed" if not
    """
    alt_urls = extract_alternative_urls(hn_text, original_url)
    
    for alt_url in alt_urls:
        # Try newspaper3k first on the alternative
        text, status = try_newspaper3k(alt_url)
        if text and not looks_like_js_warning(text):
            return text, "full_alt"
        
        # Try Playwright on the alternative
        text, status = try_playwright(alt_url)
        if text and not looks_like_js_warning(text):
            return text, "full_alt"
    
    return None, "failed"


def try_newspaper3k(url: str, timeout: int = 10) -> Tuple[Optional[str], str]:
    """
    Try to extract article text using newspaper3k (fast, no JS).
    
    Args:
        url: Article URL to scrape
        timeout: Request timeout in seconds
        
    Returns:
        (text, status) tuple where:
        - text: Extracted article text or None on failure
        - status: "full" if successful, "failed" if not
    """
    try:
        article = Article(url)
        article.download()
        article.parse()
        
        text = article.text
        
        if text and len(text.strip()) > 100:
            return text.strip(), "full"
        else:
            return None, "failed"
            
    except Exception as e:
        return None, "failed"


def try_playwright(url: str, timeout: int = 30000) -> Tuple[Optional[str], str]:
    """
    Try to extract article text using Playwright (slow, handles JS).
    
    Uses headless Chromium to render the page and extract text content.
    Includes stealth techniques to avoid bot detection.
    
    Args:
        url: Article URL to scrape
        timeout: Page load timeout in milliseconds
        
    Returns:
        (text, status) tuple where:
        - text: Extracted article text or None on failure
        - status: "full_js" if successful, "failed" if not
    """
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Use headless=new mode for better stealth (if supported)
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='America/Los_Angeles',
            )
            page = context.new_page()
            
            # Additional stealth: Remove webdriver flag
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)
            
            try:
                page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                
                # Wait a bit for JS to render
                page.wait_for_timeout(2000)
                
                # Try to get article content from common selectors (ordered by specificity)
                selectors = [
                    "article .article-body",
                    "article .post-body",
                    "article .entry-content",
                    ".article-content",
                    ".article-body",
                    ".post-content",
                    ".post-body",
                    ".entry-content",
                    ".story-body",
                    ".story-content",
                    "[itemprop='articleBody']",
                    "[role='article']",
                    "article",
                    "main article",
                    "main .content",
                    "main",
                    "#content",
                    ".content",
                ]
                
                best_text = None
                best_length = 0
                
                for selector in selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        for element in elements:
                            text = element.inner_text()
                            if text and len(text.strip()) > best_length:
                                best_text = text.strip()
                                best_length = len(best_text)
                                # If we found something good, use it
                                if best_length > 1000:
                                    break
                        if best_length > 1000:
                            break
                    except:
                        continue
                
                # Fallback to body text if nothing good found
                if best_length < 200:
                    try:
                        # Remove nav, footer, header before extracting body
                        page.evaluate("""
                            document.querySelectorAll('nav, footer, header, aside, .sidebar, .comments, .advertisement, .ad').forEach(el => el.remove());
                        """)
                        body_text = page.inner_text("body")
                        if body_text and len(body_text.strip()) > best_length:
                            best_text = body_text.strip()
                            best_length = len(best_text)
                    except:
                        pass
                
                if best_text and best_length > 200:
                    return best_text, "full_js"
                else:
                    return None, "failed"
                    
            finally:
                browser.close()
                
    except Exception as e:
        return None, "failed"


def fetch_article_text(url: str, hn_text: str = "") -> Tuple[str, str]:
    """
    Fetch article text using multi-tier fallback chain.
    
    Fallback order:
    1. newspaper3k (fast, static HTML) - skip for known-bad domains
    2. Playwright (headless browser for JS-heavy sites)
    3. Wayback Machine (archived version)
    4. Alternative URLs from HN post text
    5. Give up (title_only)
    
    Args:
        url: Article URL to scrape
        hn_text: Optional HN post text that may contain alternative URLs
        
    Returns:
        (text, status) tuple where:
        - text: Extracted article text (or empty string on failure)
        - status: "full" (newspaper3k), "full_js" (Playwright), 
                  "full_archive" (Wayback), "full_alt" (alternative URL),
                  or "title_only" (all failed)
    """
    if not url:
        return "", "title_only"
    
    # Tier 1: Try newspaper3k (fast path)
    text, status = try_newspaper3k(url)
    if text and not looks_like_js_warning(text):
        return text, "full"
    
    # Tier 2: Fall back to Playwright for JS-heavy pages
    text, status = try_playwright(url)
    if text and not looks_like_js_warning(text):
        return text, "full_js"
    
    # Tier 3: Try Wayback Machine archive
    text, status = try_wayback(url)
    if text:
        return text, "full_archive"
    
    # Tier 4: Try alternative URLs from HN post text
    if hn_text:
        text, status = try_alternative_urls(hn_text, url)
        if text:
            return text, "full_alt"
    
    # All tiers failed
    return "", "title_only"


if __name__ == "__main__":
    # Test with sample URLs
    import sys
    
    test_urls = [
        # Normal article (should work with newspaper3k)
        "https://arstechnica.com/science/2024/01/some-recent-article/",
        # JS-heavy (might need Playwright)
        "https://www.bloomberg.com/",
    ]
    
    if len(sys.argv) > 1:
        test_urls = sys.argv[1:]
    
    for url in test_urls:
        print(f"\n{'='*60}")
        print(f"Testing: {url}")
        print('='*60)
        
        # Test newspaper3k
        start = time.time()
        text_n, status_n = try_newspaper3k(url)
        time_n = time.time() - start
        print(f"\nnewspaper3k ({time_n:.2f}s): {status_n}")
        if text_n:
            print(f"  Length: {len(text_n)} chars")
            print(f"  Preview: {text_n[:200]}...")
            print(f"  JS warning: {looks_like_js_warning(text_n)}")
        
        # Test Playwright
        start = time.time()
        text_p, status_p = try_playwright(url)
        time_p = time.time() - start
        print(f"\nPlaywright ({time_p:.2f}s): {status_p}")
        if text_p:
            print(f"  Length: {len(text_p)} chars")
            print(f"  Preview: {text_p[:200]}...")
            print(f"  JS warning: {looks_like_js_warning(text_p)}")
        
        # Test hybrid
        start = time.time()
        text_h, status_h = fetch_article_text(url)
        time_h = time.time() - start
        print(f"\nHybrid ({time_h:.2f}s): {status_h}")
        if text_h:
            print(f"  Length: {len(text_h)} chars")
            print(f"  Preview: {text_h[:200]}...")
