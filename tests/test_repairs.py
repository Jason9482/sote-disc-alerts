"""Synthetic offline tests for store-repair-1. Not evidence of live store stock."""
import gzip
import json
import time
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import requests

from sote.engine import SCANNER_REVISION, scan_source, health_text
from sote.http import StoreClient, FetchError, RobotsRules
from sote.parsers import sitemap_links
from sote.model import canonical_url

BASE = 'https://store.example'
URL = BASE + '/product/elden-ring-shadow-of-the-erdtree-ps5/'
TITLE = 'Elden Ring Shadow of the Erdtree Edition PS5'
SOURCE = {'id': 'repair', 'name': 'Repair demo', 'base': BASE, 'products': [],
          'catalogues': [], 'sitemap_discovery': True}
PAGE = '<h1 class="product_title">' + TITLE + '</h1>'
MAP = '<urlset><url><loc>' + URL + '</loc></url></urlset>'


def response(body: bytes, status=200):
    r = Mock()
    r.status_code = status
    r.headers = {}
    r.encoding = 'utf-8'
    r.iter_content.side_effect = lambda *a, **kw: iter([body])
    return r


class SitemapRepairTests(unittest.TestCase):
    def test_repairs_bare_ampersand(self):
        warnings = []
        xml = '<urlset><url><loc>' + URL + '?id=1&pid=2</loc></url></urlset>'
        children, found = sitemap_links(xml, BASE, warnings)
        self.assertEqual(found, [URL + '?id=1&pid=2'])
        self.assertTrue(warnings)
    def test_escaped_ampersand_unchanged(self):
        warnings = []
        xml = '<urlset><url><loc>' + URL + '?id=1&amp;pid=2</loc></url></urlset>'
        self.assertEqual(sitemap_links(xml, BASE, warnings)[1], [URL + '?id=1&pid=2'])
        self.assertEqual(warnings, [])
    def test_cdata_not_double_escaped(self):
        warnings = []
        xml = '<urlset><url><loc><![CDATA[' + URL + '?id=1&pid=2]]></loc><title>A&B</title></url></urlset>'
        self.assertEqual(sitemap_links(xml, BASE, warnings)[1], [URL + '?id=1&pid=2'])
    def test_truncated_xml_still_fails(self):
        with self.assertRaises(ET.ParseError):
            sitemap_links(MAP[:-5], BASE)
    def test_mismatched_tags_still_fail(self):
        with self.assertRaises(ET.ParseError):
            sitemap_links('<urlset><url><loc>' + URL + '</url></loc></urlset>', BASE)
    def test_valid_html_is_not_empty_sitemap(self):
        with self.assertRaises(ValueError):
            sitemap_links('<html><body>Search unavailable</body></html>', BASE)
    def test_entity_declaration_still_rejected(self):
        with self.assertRaises(ValueError):
            sitemap_links('<!DOCTYPE a [<!ENTITY ext SYSTEM "file:///etc/passwd">]><urlset/>', BASE)
    def test_bom_and_whitespace_before_declaration(self):
        xml = '\ufeff \n<?xml version="1.0"?>' + MAP
        self.assertEqual(sitemap_links(xml, BASE)[1], [URL])
    def test_nested_image_loc_not_a_product(self):
        xml = '<urlset xmlns:image="http://example.org/image"><url><loc>' + BASE + '/ordinary-game</loc><image:image><image:loc>' + URL + 'image.jpg</image:loc></image:image></url></urlset>'
        self.assertEqual(sitemap_links(xml, BASE)[1], [])
    def test_sitemap_title_can_discover_opaque_product_url(self):
        opaque = BASE + '/product/12345'
        xml = '<urlset xmlns:image="http://example.org/image"><url><loc>' + opaque + '</loc><image:image><image:title>' + TITLE + '</image:title></image:image></url></urlset>'
        self.assertEqual(sitemap_links(xml, BASE)[1], [opaque])
    def test_namespaced_sitemap(self):
        self.assertEqual(sitemap_links(MAP.replace('<urlset>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'), BASE)[1], [URL])
    def test_external_sitemap_and_product_rejected(self):
        self.assertEqual(sitemap_links(MAP.replace(BASE, 'https://other.example'), BASE)[1], [])
        xml = '<sitemapindex><sitemap><loc>https://other.example/products.xml</loc></sitemap></sitemapindex>'
        self.assertEqual(sitemap_links(xml, BASE), ([], []))
    def test_stock_words_in_map_never_create_stock_result(self):
        xml = MAP.replace('</url>', '<availability>InStock</availability></url>')
        self.assertEqual(sitemap_links(xml, BASE), ([], [URL]))


class HTTPRepairTests(unittest.TestCase):
    def test_ordinary_page_retains_four_mb_limit(self):
        r = response(b'x' * 4_000_001)
        with self.assertRaises(FetchError):
            StoreClient._read(r)
        r.close.assert_called_once()
    def test_larger_sitemap_body_supported(self):
        body = b'x' * 4_000_001
        self.assertEqual(len(StoreClient._read(response(body), max_bytes=52_428_800)), len(body))
    def test_gzip_document_supported(self):
        self.assertEqual(StoreClient._read(response(gzip.compress(MAP.encode())), allow_gzip=True), MAP)
    def test_expanded_gzip_limit_enforced(self):
        with self.assertRaises(FetchError):
            StoreClient._read(response(gzip.compress(b'x' * 10000)), max_bytes=1000, allow_gzip=True)
    def test_invalid_gzip_fails(self):
        with self.assertRaises(FetchError):
            StoreClient._read(response(b'\x1f\x8bgarbage'), allow_gzip=True)
    def test_truncated_download_fails_and_closes(self):
        r = response(b'')
        r.iter_content.side_effect = requests.exceptions.ChunkedEncodingError('truncated')
        with self.assertRaises(FetchError):
            StoreClient._read(r)
        r.close.assert_called_once()
    def test_get_sitemap_uses_larger_limit(self):
        c = StoreClient(SOURCE, {}, {})
        c.robots = RobotsRules()
        c.robots.parse(['User-agent: *', 'Allow: /'])
        c._request = Mock(return_value=response(b'x' * 4_000_001))
        self.assertEqual(len(c.get_sitemap(BASE + '/sitemap.xml')), 4_000_001)
    def test_get_sitemap_still_respects_robots(self):
        c = StoreClient(SOURCE, {}, {})
        c.robots = RobotsRules()
        c.robots.parse(['User-agent: *', 'Disallow: /'])
        c._request = Mock()
        with self.assertRaises(FetchError):
            c.get_sitemap(BASE + '/sitemap.xml')
        c._request.assert_not_called()
    def test_tls_diagnostic_no_secret_leak(self):
        c = StoreClient(SOURCE, {}, {'request_delay_seconds': 0})
        c.session.get = Mock(side_effect=requests.exceptions.SSLError('secret-value'))
        with self.assertRaises(FetchError) as caught:
            c._request(URL)
        self.assertIn('TLS', str(caught.exception))
        self.assertNotIn('secret-value', str(caught.exception))
        self.assertNotIn('verify', c.session.get.call_args.kwargs)
    def test_timeout_diagnostic(self):
        c = StoreClient(SOURCE, {}, {'request_delay_seconds': 0})
        c.session.get = Mock(side_effect=requests.exceptions.Timeout())
        with self.assertRaises(FetchError) as caught:
            c._request(URL)
        self.assertIn('timed out', str(caught.exception))
    def test_dns_diagnostic(self):
        c = StoreClient(SOURCE, {}, {'request_delay_seconds': 0})
        c.session.get = Mock(side_effect=requests.exceptions.ConnectionError('Failed to resolve secret-url'))
        with self.assertRaises(FetchError) as caught:
            c._request(URL)
        self.assertIn('DNS', str(caught.exception))
        self.assertNotIn('secret-url', str(caught.exception))
    def test_http_status_recorded(self):
        c = StoreClient(SOURCE, {}, {})
        c.robots = RobotsRules()
        c.robots.parse(['User-agent: *', 'Allow: /'])
        c._request = Mock(return_value=response(b'', 404))
        with self.assertRaises(FetchError) as caught:
            c.get(URL)
        self.assertEqual(caught.exception.status_code, 404)


def fake_factory(pages, declared=()):
    instances = []
    class FakeClient:
        def __init__(self, source, state, config):
            self.calls = 0
            self.urls = []
            self.robots = Mock()
            self.robots.site_maps.return_value = list(declared)
            self.state = state
            instances.append(self)
        def load_robots(self):
            if self.state.get('cooldown_until', 0) > time.time():
                raise FetchError('Store is in a temporary backoff window')
        def get(self, url):
            self.calls += 1
            self.urls.append(url)
            item = pages.get(url, FetchError('HTTP 404; not a stock result', status_code=404))
            if isinstance(item, Exception):
                raise item
            return item
        get_sitemap = get
    return FakeClient, instances


class DiscoveryRepairTests(unittest.TestCase):
    def test_missing_default_uses_fallback(self):
        factory, clients = fake_factory({BASE + '/sitemap_index.xml': MAP, canonical_url(URL): PAGE})
        items, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertEqual(report['product_pages'], 1)
        self.assertEqual(items[0].status, 'unknown')
        self.assertEqual(report['discovery_pages'], 1)
        self.assertIn(BASE + '/sitemap_index.xml', clients[0].urls)
    def test_second_declared_sitemap_not_discarded(self):
        first, second = BASE + '/broken.xml', BASE + '/products.xml'
        factory, _ = fake_factory({first: '<broken', second: MAP, canonical_url(URL): PAGE}, [first, second])
        items, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertEqual(report['product_pages'], 1)
        self.assertEqual(len(report['sitemap_attempts']), 2)
    def test_child_map_is_prioritized(self):
        index = '<sitemapindex><sitemap><loc>' + BASE + '/product-sitemap.xml</loc></sitemap></sitemapindex>'
        factory, clients = fake_factory({BASE + '/sitemap.xml': index, BASE + '/product-sitemap.xml': MAP, canonical_url(URL): PAGE})
        items, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertEqual(report['product_pages'], 1)
        self.assertNotIn(BASE + '/wp-sitemap.xml', clients[0].urls)
    def test_403_does_not_try_alternate_maps(self):
        factory, clients = fake_factory({BASE + '/sitemap.xml': FetchError('blocked', status_code=403), BASE + '/sitemap_index.xml': MAP})
        items, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertEqual(clients[0].urls, [BASE + '/sitemap.xml'])
        self.assertFalse(items)
    def test_no_bypass_of_existing_cooldown(self):
        state = {'cooldown_until': time.time() + 3600}
        factory, clients = fake_factory({BASE + '/sitemap.xml': MAP})
        scan_source(SOURCE, state, {}, time.time(), client_factory=factory)
        self.assertEqual(clients[0].urls, [])
        self.assertGreater(state['cooldown_until'], time.time())
    def test_revision_rechecks_once_preserving_known_urls(self):
        now = time.time()
        state = {'discovery_at': now, 'known': {canonical_url(URL): now}}
        factory, _ = fake_factory({BASE + '/sitemap.xml': '<urlset/>', canonical_url(URL): PAGE})
        items, first = scan_source(SOURCE, state, {}, now, client_factory=factory)
        _, second = scan_source(SOURCE, state, {}, now + 60, client_factory=factory)
        self.assertEqual(first['discovery_pages'], 1)
        self.assertEqual(second['discovery_pages'], 0)
        self.assertEqual(state['scanner_revision'], SCANNER_REVISION)
        self.assertIn(canonical_url(URL), state['known'])
    def test_html_page_not_counted_as_successful_discovery(self):
        factory, _ = fake_factory({BASE + '/sitemap.xml': '<html><body>Not found</body></html>'})
        _, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertEqual(report['discovery_pages'], 0)
        self.assertTrue(report['errors'])
    def test_map_request_limit_preserved(self):
        maps = [BASE + '/sitemap' + str(i) + '.xml' for i in range(6)]
        factory, clients = fake_factory({}, maps)
        _, report = scan_source(SOURCE, {}, {'sitemap_pages': 2}, time.time(), client_factory=factory)
        self.assertEqual(len(report['sitemap_attempts']), 2)
        self.assertEqual(len(clients[0].urls), 2)
    def test_sitemap_repair_warning_is_reported(self):
        xml = MAP.replace('</loc>', '?id=1&pid=2</loc>')
        factory, _ = fake_factory({BASE + '/sitemap.xml': xml})
        _, report = scan_source(SOURCE, {}, {}, time.time(), client_factory=factory)
        self.assertTrue(any('ampersands' in x for x in report['warnings']))
    def test_multiple_root_indexes_rotate_across_discovery_runs(self):
        first, second = BASE + '/first.xml', BASE + '/second.xml'
        child = BASE + '/product.xml'
        index = '<sitemapindex><sitemap><loc>' + child + '</loc></sitemap></sitemapindex>'
        factory, clients = fake_factory({first: index, second: '<urlset/>', child: '<urlset/>'}, [first, second])
        state = {}
        now = time.time()
        scan_source(SOURCE, state, {'sitemap_pages': 2}, now, client_factory=factory)
        scan_source(SOURCE, state, {'sitemap_pages': 2}, now + 7 * 3600, client_factory=factory)
        self.assertEqual(clients[0].urls[0], first)
        self.assertEqual(clients[1].urls[0], second)
    def test_health_shows_revision_and_separate_reddit(self):
        text = health_text([], {}, 'off in GitHub; external MonitoRSS feeds are separate and not checked here')
        self.assertIn(SCANNER_REVISION, text)
        self.assertIn('MonitoRSS', text)


if __name__ == '__main__':
    unittest.main()
