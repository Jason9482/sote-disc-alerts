"""Synthetic regression fixtures for repair 2. No live stock assertions."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sote.discovery import ordered_child_maps, sitemap_priority
from sote.engine import scan_source, write_run_summary, SCANNER_REVISION, event_for
from sote.model import Listing, canonical_url
from sote.parsers import parse_html, sitemap_links, stock_label
from sote.http import FetchError
from test_repairs import fake_factory

BASE = 'https://store.example'
URL = BASE + '/product/elden-ring-shadow-of-the-erdtree-ps5/'
TITLE = 'Elden Ring Shadow of the Erdtree Edition PS5'
SOURCE = {'id': 'demo2', 'name': 'Demo 2', 'base': BASE, 'sitemap_discovery': True,
          'products': [], 'catalogues': []}


def page(body='', offer=None):
    html = '<div class="summary"><h1 class="product_title">' + TITLE + '</h1>' + body + '</div>'
    if offer:
        data = {'@type': 'Product', 'name': TITLE, 'offers': {'availability': 'https://schema.org/' + offer}}
        html += '<script type="application/ld+json">' + json.dumps(data) + '</script>'
    return html


def index(children):
    return '<sitemapindex>' + ''.join('<sitemap><loc>' + u + '</loc></sitemap>' for u in children) + '</sitemapindex>'


def product_map(url=URL):
    return '<urlset><url><loc>' + url + '</loc></url></urlset>'


class OrderingTests(unittest.TestCase):
    def test_ps5_before_cameras(self):
        urls = [BASE + '/product-sitemap-camera-lens.xml', BASE + '/product-sitemap-cameras.xml', BASE + '/product-sitemap-ps5-games.xml']
        self.assertEqual(ordered_child_maps(urls, BASE, {})[0], urls[2])
    def test_product_before_brand(self):
        self.assertLess(sitemap_priority(BASE + '/product-sitemap.xml'), sitemap_priority(BASE + '/product_brand-sitemap.xml'))
    def test_product_before_category(self):
        self.assertLess(sitemap_priority(BASE + '/product-sitemap.xml'), sitemap_priority(BASE + '/product_cat-sitemap.xml'))
    def test_category_containing_ps5_still_low_priority(self):
        self.assertGreater(sitemap_priority(BASE + '/product-category-ps5.xml'), sitemap_priority(BASE + '/product-sitemap.xml'))
    def test_domain_games_does_not_change_category_rank(self):
        self.assertEqual(sitemap_priority('https://games.example/sitemap.xml'), sitemap_priority(BASE + '/sitemap.xml'))
    def test_ps5_controller_map_not_treated_as_game_map(self):
        self.assertGreater(sitemap_priority(BASE + '/product-sitemap-ps5-controllers.xml'), sitemap_priority(BASE + '/product-sitemap-games.xml'))
    def test_unknown_maps_remain_candidates(self):
        a = BASE + '/opaque-map.xml'
        self.assertEqual(ordered_child_maps([a], BASE, {}), [a])
    def test_same_priority_uses_least_recently_attempted(self):
        a, b = BASE + '/product-sitemap.xml', BASE + '/product-sitemap2.xml'
        self.assertEqual(ordered_child_maps([a, b], BASE, {a:100}), [b, a])
    def test_offsite_and_duplicates_filtered(self):
        a = BASE + '/product-sitemap.xml'
        self.assertEqual(ordered_child_maps([a, a, 'https://other.example/ps5.xml'], BASE, {}), [a])
    def test_dacby_shaped_index_uses_games_in_three_map_budget(self):
        cameras = [BASE + '/product-sitemap-camera-lens.xml', BASE + '/product-sitemap-cameras.xml']
        games = [BASE + '/product-sitemap-ps5-games.xml', BASE + '/product-sitemap-ps4-games.xml']
        children = cameras + games
        pages = {BASE + '/sitemap.xml': index(children), **{u: '<urlset/>' for u in children}}
        factory, clients = fake_factory(pages)
        scan_source(SOURCE, {}, {'sitemap_pages':3}, time.time(), client_factory=factory)
        self.assertEqual(clients[0].urls[1:3], games)
    def test_gamebuy_shaped_index_does_not_spend_budget_on_taxonomy_first(self):
        children = [BASE + '/product_brand-sitemap.xml', BASE + '/product_cat-sitemap.xml', BASE + '/product-sitemap.xml']
        pages = {BASE + '/sitemap.xml': index(children), children[-1]: product_map(), canonical_url(URL): page('<p class="stock out-of-stock">Out of stock</p>')}
        factory, clients = fake_factory(pages)
        items, report = scan_source(SOURCE, {}, {'sitemap_pages':2}, time.time(), client_factory=factory)
        self.assertEqual(clients[0].urls[1], children[-1])
        self.assertEqual(items[0].status, 'out_of_stock')
        self.assertEqual(report['product_pages'], 1)
    def test_same_priority_maps_rotate_across_runs(self):
        children = [BASE + '/product-sitemap' + str(i) + '.xml' for i in range(3)]
        pages = {BASE + '/sitemap.xml': index(children), **{u:'<urlset/>' for u in children}}
        factory, clients = fake_factory(pages)
        state = {}; now = time.time()
        for t in [now, now+7*3600, now+14*3600]:
            scan_source(SOURCE, state, {'sitemap_pages':2}, t, client_factory=factory)
        self.assertEqual([c.urls[1] for c in clients], children)
    def test_revision_forces_discovery_without_erasing_state(self):
        now=time.time(); state={'scanner_revision':'store-repair-1','discovery_at':now,'known':{canonical_url(URL):now}, 'untouched':'yes'}
        factory, clients = fake_factory({BASE+'/sitemap.xml':'<urlset/>', canonical_url(URL):page()})
        scan_source(SOURCE,state,{},now,client_factory=factory)
        self.assertIn(BASE+'/sitemap.xml',clients[0].urls)
        self.assertEqual(state['scanner_revision'],SCANNER_REVISION)
        self.assertEqual(state['untouched'],'yes')
        self.assertIn(canonical_url(URL),state['known'])
    def test_access_block_still_stops_discovery(self):
        factory, clients = fake_factory({BASE+'/sitemap.xml':FetchError('Blocked',status_code=403)})
        _, r = scan_source(SOURCE,{}, {},time.time(),client_factory=factory)
        self.assertEqual(clients[0].urls,[BASE+'/sitemap.xml'])
        self.assertEqual(r['discovery_pages'],0)


class StockSignalTests(unittest.TestCase):
    def result(self, body, offer=None):
        return parse_html(page(body, offer), SOURCE, URL)[0]
    def test_out_of_stock_wins_over_generic_preorder_policy(self):
        x=self.result('<p class="stock out-of-stock">Out of stock</p><p>Pre-order items ship after release.</p>')
        self.assertEqual(x.status,'out_of_stock')
    def test_waitlist_is_not_stock(self):
        x=self.result('<p class="stock out-of-stock">Out of stock</p><button>Notify me when available</button>')
        self.assertEqual(x.status,'out_of_stock')
    def test_policy_does_not_create_backorder(self):
        x=self.result('<p>Preorder policy: contact us for delivery times</p>')
        self.assertEqual(x.status,'unknown')
    def test_generic_preorder_paragraph_not_override_instock(self):
        x=self.result('<p class="stock in-stock">In stock</p><p>For preorders, dispatch is on release day</p>')
        self.assertEqual(x.status,'in_stock')
    def test_explicit_backorder_still_recognized(self):
        x=self.result('<p>Available on backorder</p><button name="add-to-cart">Add</button>')
        self.assertEqual(x.status,'backorder')
        self.assertIsNone(event_for(x,{},time.time(),{}))
    def test_explicit_preorder_still_recognized(self):
        self.assertEqual(self.result('<p>Available for pre-order</p>').status,'backorder')
    def test_hidden_preorder_not_override_in_stock(self):
        x=self.result('<p class="stock in-stock">In stock</p><p hidden>Available on backorder</p>')
        self.assertEqual(x.status,'in_stock')
    def test_inline_hidden_outofstock_not_override_instock(self):
        x=self.result('<p class="stock in-stock">In stock</p><p style="display: none" class="stock out-of-stock">Out of stock</p>')
        self.assertEqual(x.status,'in_stock')
    def test_aria_hidden_unavailable_template_ignored(self):
        x=self.result('<p class="stock in-stock">In stock</p><div aria-hidden="true"><p class="stock out-of-stock">Out of stock</p></div>')
        self.assertEqual(x.status,'in_stock')
    def test_nested_hidden_elements_do_not_crash(self):
        x=self.result('<div hidden><span hidden>Available on backorder</span></div>')
        self.assertEqual(x.status,'unknown')
    def test_related_item_inside_scope_ignored(self):
        x=self.result('<p class="stock in-stock">In stock</p><div class="related"><p class="stock out-of-stock">Out of stock</p></div>')
        self.assertEqual(x.status,'in_stock')
    def test_stock_label_versus_structured_offer_conflict_not_strong_alert(self):
        x=self.result('<p class="stock in-stock">In stock</p>', 'OutOfStock')
        self.assertEqual(x.status,'unknown')
        self.assertNotEqual(event_for(x,{},time.time(),{}),'IN-STOCK LEAD')
    def test_cart_button_cannot_overrule_unavailable_offer(self):
        x=self.result('<button name="add-to-cart">Add to cart</button>', 'OutOfStock')
        self.assertEqual(x.status,'unknown')
    def test_outofstock_explicit_overrides_structured_instock(self):
        self.assertEqual(self.result('<p class="stock out-of-stock">Out of stock</p>', 'InStock').status, 'out_of_stock')
    def test_disabled_backorders_phrase_not_backorder(self):
        self.assertIsNone(stock_label('Backorders not allowed'))
    def test_preorder_policy_not_stock_label(self):
        self.assertIsNone(stock_label('Preorder policy: delivery times apply'))
    def variant(self, text, available=True):
        data=[{'variation_id':9,'attributes':{'attribute_condition':'pre-owned'}, 'is_in_stock':available, 'is_purchasable':True,'availability_html':text}]
        form='<form class="variations_form" data-product_variations=\''+json.dumps(data)+'\'></form>'
        return self.result(form)
    def test_variant_backorders_not_allowed_does_not_override_stock(self):
        self.assertEqual(self.variant('<p>Backorders not allowed</p>').status,'in_stock')
    def test_variant_positive_backorder_recognized(self):
        x=self.variant('<p class="stock available-on-backorder">Available on backorder</p>')
        self.assertEqual(x.status,'backorder')
        self.assertEqual(x.variant,'pre-owned')
    def test_unavailable_variant_not_changed_by_backorder_copy(self):
        self.assertEqual(self.variant('<p>Available on backorder</p>',False).status,'out_of_stock')


class DiagnosticTests(unittest.TestCase):
    def test_counts_opaque_links_without_treating_as_products(self):
        stats={}; url=BASE+'/product/12a45678-1234-1234-1234-12345678abcd'
        _, leads=sitemap_links(product_map(url),BASE,stats=stats)
        self.assertEqual(leads,[])
        self.assertEqual(stats,{'page_urls':1,'opaque_without_title':1})
    def test_cex_shaped_boxid_counted(self):
        stats={}; _, leads=sitemap_links(product_map(BASE+'/sell/product-detail?id=99&amp;boxId=1234'),BASE,stats=stats)
        self.assertEqual(stats['opaque_without_title'],1)
        self.assertEqual(leads,[])
    def test_identifying_sitemap_title_allows_candidate(self):
        url=BASE+'/product/12a45678-1234-1234-1234-12345678abcd'
        xml=product_map(url).replace('</url>','<title>'+TITLE+'</title></url>');stats={}
        self.assertEqual(sitemap_links(xml,BASE,stats=stats)[1],[url])
        self.assertEqual(stats['opaque_without_title'],0)
    def test_descriptive_url_with_id_not_marked_opaque(self):
        stats={};sitemap_links(product_map(URL+'?id=9'),BASE,stats=stats)
        self.assertEqual(stats['opaque_without_title'],0)
    def test_opaque_gap_appears_in_report(self):
        factory, _=fake_factory({BASE+'/sitemap.xml':product_map(BASE+'/product/12a45678-1234-1234-1234-12345678abcd')})
        _, report=scan_source(SOURCE,{}, {}, time.time(),client_factory=factory)
        self.assertTrue(any('editions were NOT checked' in w for w in report['warnings']))
        self.assertEqual(report['product_pages'],0)
    def test_summary_includes_evidence_and_revision(self):
        with tempfile.TemporaryDirectory() as d:
            old=os.getcwd();os.chdir(d)
            try:
                with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}):
                    txt=write_run_summary([], [Listing('Demo',TITLE,URL,status='out_of_stock',evidence='Primary product unavailable')], [])
                self.assertIn('Evidence: Primary product unavailable',txt)
                self.assertIn('store-repair-2',txt)
            finally:
                os.chdir(old)

if __name__=='__main__':
    unittest.main()
