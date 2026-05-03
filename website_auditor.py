import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urlparse, urljoin
import time
import re
import argparse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WebsiteAuditor:
    def __init__(self, start_url, max_pages=100):
        self.start_url = start_url
        if not self.start_url.startswith('http'):
            self.start_url = 'https://' + self.start_url

        self.domain = urlparse(self.start_url).netloc
        self.visited_urls = set()
        self.urls_to_visit = set([self.start_url])
        self.max_pages = max_pages

        # Data storage for Excel sheets
        self.page_audit_data = []
        self.broken_links_data = []
        self.images_data = []

        # Use session to keep connections alive
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def is_internal_url(self, url):
        parsed = urlparse(url)
        return parsed.netloc == self.domain or parsed.netloc == ''

    def normalize_url(self, url, base_url):
        joined = urljoin(base_url, url)
        parsed = urlparse(joined)
        # Remove fragments
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def get_page_metrics(self, url):
        start_time = time.time()
        try:
            response = self.session.get(url, timeout=10)
            response_time = time.time() - start_time
            status_code = response.status_code

            if status_code != 200:
                logger.warning(f"Failed to fetch {url} - Status: {status_code}")
                return None, status_code, response_time

            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type:
                return None, status_code, response_time

            soup = BeautifulSoup(response.text, 'html.parser')
            return soup, status_code, response_time

        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            response_time = time.time() - start_time
            return None, 0, response_time

    def audit_page(self, url):
        logger.info(f"Auditing: {url}")
        self.visited_urls.add(url)

        soup, status_code, response_time = self.get_page_metrics(url)

        page_info = {
            'URL': url,
            'Status Code': status_code,
            'Response Time (s)': round(response_time, 2),
            'Title': '',
            'Title Length': 0,
            'Meta Description': '',
            'Meta Desc Length': 0,
            'H1 Count': 0,
            'Word Count': 0,
            'Total Links': 0,
            'Internal Links': 0,
            'External Links': 0,
            'Total Images': 0,
            'Images Missing Alt': 0
        }

        if soup is None:
            self.page_audit_data.append(page_info)
            return

        # Extract SEO elements
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            page_info['Title'] = title_tag.string.strip()
            page_info['Title Length'] = len(page_info['Title'])

        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            page_info['Meta Description'] = meta_desc['content'].strip()
            page_info['Meta Desc Length'] = len(page_info['Meta Description'])

        h1_tags = soup.find_all('h1')
        page_info['H1 Count'] = len(h1_tags)

        # Calculate word count (rough estimate)
        text_content = soup.get_text(separator=' ')
        words = re.findall(r'\b\w+\b', text_content)
        page_info['Word Count'] = len(words)

        # Analyze Links
        links = soup.find_all('a', href=True)
        page_info['Total Links'] = len(links)

        for link in links:
            href = link['href']
            if href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue

            full_url = self.normalize_url(href, url)
            is_internal = self.is_internal_url(full_url)

            if is_internal:
                page_info['Internal Links'] += 1
                if full_url not in self.visited_urls and len(self.visited_urls) + len(self.urls_to_visit) < self.max_pages:
                    self.urls_to_visit.add(full_url)
            else:
                page_info['External Links'] += 1

            # Check if link is broken (simplistic check to save time, only checking structure here)
            # A more robust script would ping each link, but that takes very long.
            # We'll just collect them for now.

        # Analyze Images
        images = soup.find_all('img')
        page_info['Total Images'] = len(images)

        for img in images:
            src = img.get('src', '')
            alt = img.get('alt', '')

            has_alt = bool(alt and alt.strip())
            if not has_alt:
                page_info['Images Missing Alt'] += 1

            self.images_data.append({
                'Page URL': url,
                'Image Source': src,
                'Alt Text': alt,
                'Has Alt Text': 'Yes' if has_alt else 'No'
            })

        self.page_audit_data.append(page_info)

    def run_audit(self):
        logger.info(f"Starting audit for {self.start_url}")

        while self.urls_to_visit and len(self.visited_urls) < self.max_pages:
            url = self.urls_to_visit.pop()
            if url not in self.visited_urls:
                self.audit_page(url)
                time.sleep(1) # Be polite

        logger.info(f"Audit complete. Audited {len(self.visited_urls)} pages.")
        self.generate_report()

    def generate_report(self):
        domain_name = self.domain.replace('.', '_').replace(':', '_')
        filename = f"{domain_name}_audit_report.xlsx"

        logger.info(f"Generating report: {filename}")

        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            if self.page_audit_data:
                df_pages = pd.DataFrame(self.page_audit_data)
                df_pages.to_excel(writer, sheet_name='Page Audit', index=False)

            if self.images_data:
                df_images = pd.DataFrame(self.images_data)
                df_images.to_excel(writer, sheet_name='Images', index=False)

        logger.info("Report generated successfully.")

def main():
    parser = argparse.ArgumentParser(description='Audit a website and generate an Excel report.')
    parser.add_argument('url', help='The starting URL of the website to audit')
    parser.add_argument('--max-pages', type=int, default=50, help='Maximum number of pages to audit (default: 50)')

    args = parser.parse_args()

    auditor = WebsiteAuditor(args.url, max_pages=args.max_pages)
    auditor.run_audit()

if __name__ == '__main__':
    main()
