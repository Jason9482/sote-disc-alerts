"""Offline, synthetic regression tests. These do NOT prove live retailer compatibility."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sote.model import Listing, canonical_url, dlc_status, is_buyback, match_title, same_site
from sote.parsers import parse_html, parse_shopify, discover_html, sitemap_links, money
from sote.engine import event_for, acknowledge, read_config, scan_source, run_scan
from sote.http import StoreClient, FetchError, robots_allowed, retry_seconds
from sote.notify import Discord, NotificationError, webhook_valid
from sote.storage import LocalStore, GitHubStore, empty_state, StorageError, validate_state
from sote.reddit import relevant, RedditClient

TITLE = 'Elden Ring Shadow of the Erdtree Edition PS5'
URL = 'https://store.example/product/elden-ring-shadow-of-the-erdtree-edition-ps5/'
SOURCE = {'id': 'demo', 'name': 'Demo', 'base': 'https://store.example', 'currency': 'INR', 'products': [URL], 'catalogues': []}
HOOK = 'https://discord.com/api/webhooks/123456/UNIT_TEST_PLACEHOLDER_NOT_A_REAL_TOKEN'


def page(content='', title=TITLE):
    return f'<html><div class="product"><div class="summary entry-summary"><h1 class="product_title">{title}</h1>{content}</div></div></html>'


class MatchingTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(match_title(TITLE), 'exact')
    def test_abbreviation(self):
        self.assertEqual(match_title('Elden Ring SOTE PS5'), 'exact')
    def test_standard_disc_rejected(self):
        self.assertEqual(match_title('Elden Ring PS5'), 'reject')
    def test_ps4_rejected(self):
        self.assertEqual(match_title(TITLE.replace('PS5', 'PS4')), 'reject')
    def test_nightreign_rejected(self):
        self.assertEqual(match_title('Elden Ring Nightreign PS5 SOTE'), 'reject')
    def test_digital_rejected(self):
        self.assertEqual(match_title(TITLE + ' Digital Download'), 'reject')
    def test_standalone_digital_rejected(self):
        self.assertEqual(match_title(TITLE + ' (Digital)'), 'reject')
    def test_collector_rejected(self):
        self.assertEqual(match_title(TITLE + ' Collector Edition'), 'reject')
    def test_code_only_rejected(self):
        self.assertEqual(match_title(TITLE + ' DLC only'), 'reject')
    def test_empty_case_rejected(self):
        self.assertEqual(match_title(TITLE + ' case only'), 'reject')
    def test_used_no_code_accepted(self):
        self.assertEqual(match_title(TITLE + ' Used without DLC code'), 'exact')
    def test_mixed_platform_possible(self):
        self.assertEqual(match_title(TITLE + ' / Xbox'), 'possible')
    def test_missing_platform_possible(self):
        self.assertEqual(match_title('Elden Ring Shadow of the Erdtree Edition'), 'possible')
    def test_url_platform_hint(self):
        self.assertEqual(match_title('Elden Ring Shadow of the Erdtree Edition', URL), 'exact')
    def test_buyback(self):
        for text in ['BUYBACK(SELL)', 'Sell your games', 'Trade-in', 'SELL']:
            self.assertTrue(is_buyback(text))
    def test_variant_preserved_in_key(self):
        self.assertNotEqual(canonical_url(URL+'?variant=1'), canonical_url(URL+'?variant=2'))
    def test_tracking_parameters_removed(self):
        self.assertEqual(canonical_url(URL+'?utm_source=foo'), canonical_url(URL))
    def test_external_host_rejected(self):
        self.assertFalse(same_site('https://store.example.evil.org/product', URL))
    def test_dlc_labels(self):
        self.assertIn('Not included', dlc_status('Pre-Owned WITHOUT DLC CODE'))
        self.assertIn('Redeemed', dlc_status('DLC already redeemed'))
        self.assertIn('Claimed unused', dlc_status('unused expansion code'))


class ParserTests(unittest.TestCase):
    def test_shopify_buyback_does_not_make_new_available(self):
        data = {'title': TITLE, 'available': True, 'variants': [
            {'id': 1, 'title': 'New', 'available': False, 'price': 360000},
            {'id': 2, 'title': 'Pre-Owned(USED)(WITHOUT DLC CODE)', 'available': False, 'price': 250000},
            {'id': 3, 'title': 'BUYBACK(SELL)', 'available': True, 'price': 170000}]}
        out = parse_shopify(data, SOURCE, URL)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(x.status == 'out_of_stock' for x in out))
        self.assertEqual(out[0].price, '3,600.00')
    def test_shopify_available_used(self):
        data = {'title': TITLE, 'variants': [{'id': 3, 'title': 'Used without DLC', 'available': True, 'price': 250000}]}
        item = parse_shopify(data, SOURCE, URL)[0]
        self.assertEqual(item.status, 'in_stock')
        self.assertIn('variant=3', item.url)
        self.assertIn('Not included', item.dlc)
    def test_shopify_nonshipping_rejected(self):
        data = {'title': TITLE, 'variants': [{'id': 1, 'title': 'New', 'available': True, 'requires_shipping': False}]}
        self.assertEqual(parse_shopify(data, SOURCE, URL), [])
    def test_shopify_html_never_uses_aggregate_stock(self):
        src = dict(SOURCE, adapter='shopify')
        item = parse_html(page('<p>Availability: Many in stock</p>'), src, URL)[0]
        self.assertEqual(item.status, 'unknown')
    def test_out_of_stock(self):
        item = parse_html(page('<p class="stock out-of-stock">Out of stock</p>'), SOURCE, URL)[0]
        self.assertEqual(item.status, 'out_of_stock')
    def test_enabled_purchase_button(self):
        item = parse_html(page('<button class="single_add_to_cart_button">Add to cart</button>'), SOURCE, URL)[0]
        self.assertEqual(item.status, 'in_stock')
    def test_backorder_not_stock(self):
        item = parse_html(page('<p>Available on backorder</p><button name="add-to-cart">Add</button>'), SOURCE, URL)[0]
        self.assertEqual(item.status, 'backorder')
    def test_recommendations_not_stock(self):
        html = page('<p class="stock out-of-stock">Out of stock</p>') + '<div class="related"><button name="add-to-cart">Add to cart</button></div>'
        self.assertEqual(parse_html(html, SOURCE, URL)[0].status, 'out_of_stock')
    def test_standard_title_with_sote_body_rejected(self):
        self.assertEqual(parse_html(page('<p>'+TITLE+'</p>', 'Elden Ring PS5'), SOURCE, URL), [])
    def test_no_primary_title_no_positive(self):
        self.assertEqual(parse_html('<h2>'+TITLE+'</h2><p>In stock</p>', SOURCE, URL), [])
    def test_schema_primary_product(self):
        data = {'@graph': [{'@type':'Product', 'name':'Another Game PS5', 'offers':{'availability':'https://schema.org/InStock'}},
                           {'@type':'Product', 'name':TITLE, 'offers':{'availability':'https://schema.org/OutOfStock'}}]}
        html = page()+'<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertEqual(parse_html(html, SOURCE, URL)[0].status, 'out_of_stock')
    def test_disabled_button_conflict(self):
        data = {'@type':'Product', 'name':TITLE, 'offers':{'availability':'https://schema.org/InStock'}}
        html = page('<button name="add-to-cart" disabled>Add</button>')+'<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertEqual(parse_html(html, SOURCE, URL)[0].status, 'unknown')
    def test_woo_variant_available(self):
        variants=[{'variation_id': 9, 'attributes':{'attribute_condition':'pre-owned'}, 'is_in_stock':True, 'is_purchasable':True, 'display_price':2800}]
        html = page('<form class="variations_form" data-product_variations=\''+json.dumps(variants)+'\'></form>')
        self.assertEqual(parse_html(html, SOURCE, URL)[0].status, 'in_stock')
    def test_woo_ajax_variants_unknown(self):
        html=page('<form class="variations_form" data-product_variations="false"></form><p>In stock</p>')
        self.assertEqual(parse_html(html, SOURCE, URL)[0].status, 'unknown')
    def test_sale_price_not_struck_price(self):
        item = parse_html(page('<p class="price"><del><span class="amount">4499</span></del><ins><span class="amount">3499</span></ins></p>'), SOURCE, URL)[0]
        self.assertEqual(item.price,'3,499.00')
    def test_discovery_never_follows_add_cart(self):
        html=f'<a href="{URL}">{TITLE}</a><a href="{URL}?add-to-cart=22">{TITLE}</a>'
        links,_=discover_html(html, 'https://store.example/shop/')
        self.assertEqual(links,[canonical_url(URL)])
    def test_sitemap_discovery(self):
        children, urls=sitemap_links('<urlset><url><loc>'+URL+'</loc></url></urlset>', SOURCE['base'])
        self.assertEqual(urls,[URL])
    def test_sitemap_external_ignored(self):
        children,urls=sitemap_links('<urlset><url><loc>https://evil.example/shadow-of-the-erdtree-ps5</loc></url></urlset>', SOURCE['base'])
        self.assertFalse(urls)
    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            sitemap_links('<!DOCTYPE foo><urlset/>', SOURCE['base'])
    def test_zero_price_unknown(self):
        self.assertEqual(money(0), 'Not verified')


class StateTests(unittest.TestCase):
    def test_initial_available_alert(self):
        self.assertEqual(event_for(Listing('Demo',TITLE,URL,status='in_stock'),{},100,{}), 'IN-STOCK LEAD')
    def test_unchanged_no_duplicate(self):
        item=Listing('Demo',TITLE,URL,status='in_stock'); state={}
        event_for(item,state,100,{}); acknowledge(item,state,'IN-STOCK LEAD')
        self.assertIsNone(event_for(item,state,200,{}))
    def test_real_restock_alert(self):
        item=Listing('Demo',TITLE,URL,status='in_stock'); state={}
        event_for(item,state,100,{}); acknowledge(item,state,'IN-STOCK LEAD')
        item.status='out_of_stock'; self.assertIsNone(event_for(item,state,200,{}))
        item.status='in_stock'; self.assertEqual(event_for(item,state,300,{}),'IN-STOCK LEAD')
    def test_unknown_does_not_fake_restock(self):
        item=Listing('Demo',TITLE,URL,status='in_stock'); state={}
        event_for(item,state,100,{}); acknowledge(item,state,'IN-STOCK LEAD')
        item.status='unknown'; event_for(item,state,200,{'alert_possible':False})
        item.status='in_stock'; self.assertIsNone(event_for(item,state,300,{}))
    def test_unacknowledged_message_retried(self):
        item=Listing('Demo',TITLE,URL,status='in_stock'); state={}
        event_for(item,state,100,{})
        self.assertEqual(event_for(item,state,200,{}),'IN-STOCK LEAD')
    def test_possible_only_once(self):
        item=Listing('Demo',TITLE,URL,status='unknown'); state={}
        self.assertEqual(event_for(item,state,100,{}),'CHECK MANUALLY')
        acknowledge(item,state,'CHECK MANUALLY')
        self.assertIsNone(event_for(item,state,200,{}))
    def test_out_never_alert(self):
        self.assertIsNone(event_for(Listing('Demo',TITLE,URL,status='out_of_stock'),{},100,{}))
    def test_price_cap(self):
        self.assertIsNone(event_for(Listing('Demo',TITLE,URL,status='in_stock',price='4,000.00'),{},100,{'max_price_inr':3000}))
    def test_local_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s=LocalStore(d+'/state.json'); state=s.load(); s.save(state); self.assertEqual(s.load(),state)
    def test_corrupt_state_not_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'; p.write_text('garbage')
            with self.assertRaises(StorageError): LocalStore(str(p)).load()
    def test_unsupported_state_not_reset(self):
        with self.assertRaises(StorageError): validate_state({'version':999})
    def test_github_read_only_error_no_empty_state(self):
        with patch.dict(os.environ, {'GITHUB_REPOSITORY':'demo/repo','GITHUB_TOKEN':'test'}):
            s=GitHubStore(); s.request=Mock(return_value=Mock(status_code=403))
            with self.assertRaises(StorageError): s.load()


class NetworkSafetyTests(unittest.TestCase):
    def test_robots_disallow(self):
        self.assertFalse(robots_allowed(['User-agent: *','Disallow: /private'], 'SOTEStockWatcher', 'https://store.example/private/x'))
    def test_robots_wildcard_query(self):
        self.assertFalse(robots_allowed(['User-agent: *','Disallow: /*?s='], 'SOTEStockWatcher', 'https://store.example/?s=elden'))
    def test_robots_longer_allow(self):
        self.assertTrue(robots_allowed(['User-agent: *','Disallow: /','Allow: /product/'], 'SOTEStockWatcher', URL))
    def test_robots_specific_group(self):
        lines=['User-agent: *','Disallow: /','User-agent: SOTEStockWatcher','Allow: /product/']
        self.assertTrue(robots_allowed(lines, 'SOTEStockWatcher', URL))
    def test_robots_end_anchor(self):
        lines=['User-agent: *','Disallow: /blocked$']
        self.assertFalse(robots_allowed(lines,'SOTEStockWatcher','https://store.example/blocked'))
        self.assertTrue(robots_allowed(lines,'SOTEStockWatcher','https://store.example/blocked/child'))
    def test_retry_after(self):
        self.assertEqual(retry_seconds('120'),120)
    def test_missing_secret_rejected(self):
        with self.assertRaises(NotificationError): Discord('')
    def test_wrong_webhook_domain_rejected(self):
        self.assertFalse(webhook_valid('https://discord.com.evil.example/api/webhooks/123/abc'))
    def test_webhook_success_wait_ack(self):
        d=Discord(HOOK); r=Mock(status_code=200); r.json.return_value={'id':'123'}; d.session.post=Mock(return_value=r)
        self.assertEqual(d.send('test'),'123')
        args=d.session.post.call_args.kwargs
        self.assertEqual(args['params'],{'wait':'true'})
        self.assertEqual(args['json']['allowed_mentions'],{'parse':[]})
    def test_webhook_failure_raises(self):
        d=Discord(HOOK); d.session.post=Mock(return_value=Mock(status_code=404))
        with self.assertRaises(NotificationError): d.send('test')
    def test_store_client_denies_external(self):
        c=StoreClient(SOURCE,{},{});
        with self.assertRaises(FetchError): c._request('https://evil.example/')
    def test_store_backoff_respected(self):
        c=StoreClient(SOURCE,{'cooldown_until':99999999999},{})
        with self.assertRaises(FetchError): c._request(URL)


class RedditTests(unittest.TestCase):
    def test_disabled_without_approval(self):
        with patch.dict(os.environ,{'REDDIT_APPROVED':'false'}):
            with self.assertRaises(Exception): RedditClient()
    def test_sale_match(self):
        self.assertTrue(relevant({'title':'[WTS] '+TITLE,'selftext':'Disc and case for sale','link_flair_text':'Sale'}))
    def test_wanted_rejected(self):
        self.assertFalse(relevant({'title':'[WTB] '+TITLE,'selftext':'looking to buy','link_flair_text':'Sale'}))
    def test_discussion_rejected(self):
        self.assertFalse(relevant({'title':TITLE,'selftext':'What is your favourite boss?'}))
    def test_sold_rejected(self):
        self.assertFalse(relevant({'title':'[WTS] '+TITLE,'selftext':'selling','link_flair_text':'SOLD'}))
    def test_removed_rejected(self):
        self.assertFalse(relevant({'title':'[WTS] '+TITLE,'selftext':'[removed]','link_flair_text':'Sale'}))
    def test_comment_sale(self):
        self.assertTrue(relevant({'body':'Selling '+TITLE+' disc and original case'}))


class IntegrationTests(unittest.TestCase):
    def test_config_valid(self):
        cfg=read_config(str(Path(__file__).resolve().parents[1]/'config.json'))
        self.assertGreater(len(cfg['sources']),0)
        self.assertIsInstance(cfg['reddit']['enabled'],bool)
    def test_source_with_synthetic_client(self):
        class FakeClient:
            def __init__(self,*args): self.calls=0
            def get(self,url):
                self.calls+=1
                return page('<p class="stock out-of-stock">Out of stock</p>')
        out,report=scan_source(SOURCE,{}, {'discovery_hours':6}, 100000, client_factory=FakeClient)
        self.assertEqual(out[0].status,'out_of_stock')
        self.assertEqual(report['product_pages'],1)
    def test_end_to_end_offline_mocked_scan(self):
        cfg={'sources':[SOURCE],'reddit':{'enabled':False}}
        item=Listing('Demo',TITLE,URL,status='in_stock')
        report={'name':'Demo','product_pages':1,'discovery_pages':0,'errors':[]}
        with tempfile.TemporaryDirectory() as d, patch('sote.engine.scan_source',return_value=([item],report)), patch('sote.engine.write_run_summary',return_value='offline test'):
            store=LocalStore(d+'/state.json'); notify=Mock()
            self.assertEqual(run_scan(cfg,store,notify),0)
            self.assertEqual(notify.listing.call_count,1)
            self.assertEqual(run_scan(cfg,store,notify),0)
            self.assertEqual(notify.listing.call_count,1)
    def test_failed_notification_not_lost(self):
        cfg={'sources':[SOURCE],'reddit':{'enabled':False}}
        item=Listing('Demo',TITLE,URL,status='in_stock')
        report={'name':'Demo','product_pages':1,'discovery_pages':0,'errors':[]}
        with tempfile.TemporaryDirectory() as d, patch('sote.engine.scan_source',return_value=([item],report)), patch('sote.engine.write_run_summary',return_value='offline test'):
            store=LocalStore(d+'/state.json'); notify=Mock(); notify.listing.side_effect=NotificationError('test failure')
            self.assertEqual(run_scan(cfg,store,notify),1)
            notify.listing.side_effect=None
            self.assertEqual(run_scan(cfg,store,notify),0)
            self.assertEqual(notify.listing.call_count,2)


if __name__=='__main__': unittest.main()
