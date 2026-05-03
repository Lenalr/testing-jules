import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urlparse, urljoin
import time
import re
import argparse
import logging
import google.generativeai as genai

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WebsiteAuditor:
    def __init__(self, start_url, max_pages=100, gemini_api_key=None):
        self.gemini_api_key = gemini_api_key
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            self.model = None

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

        # Advanced Checking
        page_info['Title Status'] = 'Missing'
        page_info['Meta Desc Status'] = 'Missing'
        page_info['Keywords'] = 'N/A'
        page_info['AI Recommendations'] = 'N/A'

        # Extract SEO elements
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            page_info['Title'] = title_tag.string.strip()
            page_info['Title Length'] = len(page_info['Title'])
            if 50 <= page_info['Title Length'] <= 60:
                page_info['Title Status'] = 'Optimal (50-60 chars)'
            elif page_info['Title Length'] < 50:
                page_info['Title Status'] = 'Too Short (<50 chars)'
            else:
                page_info['Title Status'] = 'Too Long (>60 chars)'

        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            page_info['Meta Description'] = meta_desc['content'].strip()
            page_info['Meta Desc Length'] = len(page_info['Meta Description'])
            if 150 <= page_info['Meta Desc Length'] <= 160:
                page_info['Meta Desc Status'] = 'Optimal (150-160 chars)'
            elif page_info['Meta Desc Length'] < 150:
                page_info['Meta Desc Status'] = 'Too Short (<150 chars)'
            else:
                page_info['Meta Desc Status'] = 'Too Long (>160 chars)'

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

        # Gemini AI Analysis
        if self.model and text_content:
            try:
                # Truncate text content to avoid token limits for very large pages
                snippet = text_content[:2000]
                prompt = f"""
                You are an expert SEO and web auditor. Analyze the following webpage data and provide:
                1. A comma-separated list of the top 3-5 keywords or phrases this page is targeting.
                2. A brief, actionable recommendation (1-2 sentences) on how to improve this page based on its metadata and content.

                Page Data:
                URL: {url}
                Title: {page_info['Title']}
                Meta Description: {page_info['Meta Description']}
                H1 Count: {page_info['H1 Count']}
                Word Count: {page_info['Word Count']}
                Images Missing Alt: {page_info['Images Missing Alt']}

                Content Snippet:
                {snippet}

                Format your response strictly as:
                Keywords: [keyword1, keyword2, ...]
                Recommendation: [Your recommendation here]
                """
                response = self.model.generate_content(prompt)

                # Parse the response
                lines = response.text.strip().split('\n')
                for line in lines:
                    if line.startswith('Keywords:'):
                        page_info['Keywords'] = line.replace('Keywords:', '').strip()
                    elif line.startswith('Recommendation:'):
                        page_info['AI Recommendations'] = line.replace('Recommendation:', '').strip()

            except Exception as e:
                logger.error(f"Error calling Gemini API for {url}: {e}")

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
    parser.add_argument('--gemini-api-key', type=str, default=None, help='Google Gemini API Key for AI-powered keyword extraction and recommendations')

    args = parser.parse_args()

    # Prompt for API key if not provided but want the feature
    api_key = args.gemini_api_key
    if not api_key:
        print("\n--- Optional AI Feature ---")
        use_ai = input("Would you like to use Google Gemini AI for smart keyword extraction and SEO recommendations? (y/N): ").strip().lower()
        if use_ai == 'y':
            api_key = input("Please paste your Gemini API Key: ").strip()

    auditor = WebsiteAuditor(args.url, max_pages=args.max_pages, gemini_api_key=api_key)
    auditor.run_audit()

if __name__ == '__main__':
    main()
