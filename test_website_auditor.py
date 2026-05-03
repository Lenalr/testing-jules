import unittest
from website_auditor import WebsiteAuditor
import os

class TestWebsiteAuditor(unittest.TestCase):
    def test_normalize_url(self):
        auditor = WebsiteAuditor('https://example.com')
        url = auditor.normalize_url('/path', 'https://example.com/base')
        self.assertEqual(url, 'https://example.com/path')

    def test_is_internal_url(self):
        auditor = WebsiteAuditor('https://example.com')
        self.assertTrue(auditor.is_internal_url('https://example.com/page1'))
        self.assertTrue(auditor.is_internal_url('/page2'))
        self.assertFalse(auditor.is_internal_url('https://google.com'))

    def test_run_audit(self):
        auditor = WebsiteAuditor('https://example.com', max_pages=1)
        auditor.run_audit()

        self.assertEqual(len(auditor.visited_urls), 1)
        self.assertTrue(os.path.exists('example_com_audit_report.xlsx'))

        # Cleanup
        if os.path.exists('example_com_audit_report.xlsx'):
            os.remove('example_com_audit_report.xlsx')

if __name__ == '__main__':
    unittest.main()
