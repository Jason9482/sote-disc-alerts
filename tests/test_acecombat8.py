"""Ace Combat 8 switch: synthetic tests, not live stock or delivery claims."""
from contextlib import redirect_stdout
import copy
import html
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import tracker
from sote.budget import budget_decision
from sote.engine import (SCANNER_REVISION, acknowledge, event_for, health_text,
                         read_config, run_scan, scan_source, write_run_summary)
from sote.http import StoreClient
from sote.model import Listing, canonical_url, discovery_hint, match_product, target_name
from sote.notify import Discord, NotificationError
from sote.parsers import discover_html, parse_html, parse_shopify, sitemap_links
from sote.storage import empty_state

ROOT = Path(__file__).resolve().parents[1]
TITLE = 'Ace Combat 8: Wings of Theve PS5'
URL = 'https://store.example/product/ace-combat-8-wings-of-theve-ps5/'
SOURCE = dict(id='demo', name='Synthetic store', base='https://store.example',
              products=[URL], target='acecombat8', currency='INR')
CFG = dict(target='acecombat8', sources=[SOURCE], max_price_inr=5500,
           daily_health=False, alert_possible=False, reddit=dict(enabled=False))
REPORT = dict(name='Synthetic store', product_pages=1, discovery_pages=0, errors=[])


def listing(price='5499', **kw):
    values = dict(source='Synthetic store', title=TITLE, url=URL,
                  status='in_stock', price=price)
    values.update(kw)
    return Listing(**values)


def page(content='', title=TITLE):
    return '<main><div class="product"><div class="summary"><h1 class="product_title">' + html.escape(title) + '</h1>' + content + '</div></div></main>'


def priced_page(price='5499', stock='in-stock', title=TITLE, extra=''):
    return page('<p class="price"><span class="amount">' + price + '</span></p><p class="stock ' + stock + '">' + ('In stock' if stock=='in-stock' else 'Out of stock') + '</p>' + extra, title)


class MemoryStore:
    def __init__(self, state=None): self.state = copy.deepcopy(state or empty_state())
    def load(self): return copy.deepcopy(self.state)
    def save(self, state): self.state = copy.deepcopy(state)


class AceMatchingTests(unittest.TestCase):
    def check(self, title, expected='exact', url=URL):
        self.assertEqual(match_product(title, url, 'acecombat8'), expected)
    def test_full_title(self): self.check(TITLE)
    def test_short_title(self): self.check('Ace Combat 8 PS5')
    def test_compact_title(self): self.check('AceCombat8 PS5 used')
    def test_compact_number(self): self.check('Ace Combat8 PS5')
    def test_roman_eight(self): self.check('Ace Combat VIII PlayStation 5')
    def test_uppercase_and_punctuation(self): self.check('ACE COMBAT 8 - WINGS OF THEVE (PLAYSTATION 5)')
    def test_condition_options(self):
        for label in ['New','Sealed','Used','Pre-Owned','Lenticular Edition','Standard Edition','Deluxe Edition','Disc Only','SteelBook Edition']:
            with self.subTest(label=label): self.check(TITLE+' '+label)
    def test_url_platform(self): self.check('Ace Combat 8: Wings of Theve')
    def test_subtitle_with_exact_slug(self): self.check('Wings of Theve PS5')
    def test_subtitle_without_series_slug_is_possible(self): self.check('Wings of Theve PS5','possible','https://store.example/product/game')
    def test_number_is_required(self): self.check('Ace Combat PS5','reject')
    def test_generic_ac8_not_strong_retailer_match(self): self.check('AC8 PS5','reject')
    def test_series_number_not_false_substring(self): self.check('Ace Combat 80 PS5','reject')
    def test_old_games(self):
        for name in ['Ace Combat 7: Skies Unknown PS4','Ace Combat 6 PS5','Ace Combat Zero PS5','Ace Combat Assault Horizon PS5']:
            with self.subTest(name=name): self.check(name,'reject')
    def test_old_primary_not_rescued_by_slug(self): self.check('Onimusha: Way of the Sword PS5','reject')
    def test_other_platforms(self):
        for name in ['PS4','Xbox Series X','PC','Nintendo Switch 2']:
            with self.subTest(name=name): self.check('Ace Combat 8 '+name,'reject')
    def test_mixed_platforms_possible(self): self.check(TITLE+' / Xbox','possible')
    def test_unknown_platform_possible(self): self.check('Ace Combat 8','possible','https://store.example/product/game')
    def test_buyback(self): self.check(TITLE+' BUYBACK SELL','reject')
    def test_non_disc_offers(self):
        for suffix in ['Steam Key','Digital','Shared Account','Rental','Case Only','Steel Book Only',
                       'Code in Box','Disc is not included','Preorder bonus','No Disc','DLC',
                       'Empty Case','Deposit','WTB','Soundtrack','Guide']:
            with self.subTest(suffix=suffix): self.check(TITLE+' '+suffix,'reject')
    def test_hardware_not_game(self):
        for prefix in ['Thrustmaster T.FLIGHT HOTAS NEO','Joystick','Flight Stick','Controller']:
            with self.subTest(prefix=prefix): self.check(prefix+' '+TITLE+' Edition','reject')
    def test_dtzone_compatibility_note_is_not_hardware_product(self):
        self.check('PS5 Ace Combat 8 wings of thieves (compatible with Thrustmaster t.flight simulator)')
    def test_preorder_title_can_be_identified_but_not_alerted_as_stock(self): self.check(TITLE+' Pre Order')
    def test_bad_product_not_rescued_by_description(self):
        self.assertEqual(parse_html(priced_page(title='Unrelated game PS5',extra='<div>'+TITLE+'</div>'),SOURCE,URL),[])


class AceBudgetAndEventTests(unittest.TestCase):
    def test_price_below_cap(self): self.assertEqual(event_for(listing('5499'),{},1,CFG),'IN-STOCK LEAD')
    def test_exactly_5500_included(self): self.assertEqual(event_for(listing('5500'),{},1,CFG),'IN-STOCK LEAD')
    def test_comma_price(self): self.assertEqual(event_for(listing('5,500.00'),{},1,CFG),'IN-STOCK LEAD')
    def test_one_paisa_above_cap(self): self.assertIsNone(event_for(listing('5500.01'),{},1,CFG))
    def test_retail_price_5999_suppressed(self): self.assertIsNone(event_for(listing('5999'),{},1,CFG))
    def test_unknown_price_suppressed(self): self.assertIsNone(event_for(listing('Not verified'),{},1,CFG))
    def test_foreign_currency_suppressed(self): self.assertIsNone(event_for(listing('40',currency='GBP'),{},1,CFG))
    def test_fake_prices_suppressed(self):
        for price in ['0','NaN','Infinity','-20','5500 with coupon','4000-6000','5.4k']:
            with self.subTest(price=price): self.assertIsNone(event_for(listing(price),{},1,CFG))
    def test_not_in_stock(self):
        for status in ['out_of_stock','backorder','unknown']:
            with self.subTest(status=status): self.assertIsNone(event_for(listing(status=status),{},1,CFG))
    def test_old_target_not_recorded(self):
        history={}; self.assertIsNone(event_for(listing(title='Onimusha Way of the Sword PS5'),history,1,CFG)); self.assertEqual(history,{})
    def test_variant_buyback_not_recorded(self): self.assertIsNone(event_for(listing(variant='BUYBACK'),{},1,CFG))
    def test_ambiguous_offer_suppressed(self): self.assertIsNone(event_for(listing(match='possible'),{},1,CFG))
    def test_repeat_suppressed(self):
        x=listing(); h={}; event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD'); self.assertIsNone(event_for(x,h,2,CFG))
    def test_first_drop_under_budget(self):
        x=listing('5999'); h={}; self.assertIsNone(event_for(x,h,1,CFG)); x.price='5499'; self.assertEqual(event_for(x,h,2,CFG),'IN-STOCK LEAD')
    def test_reentry_after_price_rise(self):
        x=listing(); h={}; event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.price='5999'; event_for(x,h,2,CFG); x.price='5500'; self.assertEqual(event_for(x,h,3,CFG),'IN-STOCK LEAD')
    def test_price_glitch_does_not_realert(self):
        x=listing(); h={}; event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.price='Not verified'; event_for(x,h,2,CFG); x.price='5499'; self.assertIsNone(event_for(x,h,3,CFG))
    def test_price_falls_further_within_budget_not_repeated(self):
        x=listing(); h={}; event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD'); x.price='5000'; self.assertIsNone(event_for(x,h,2,CFG))
    def test_restock_realerts(self):
        x=listing(); h={}; event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.status='out_of_stock'; event_for(x,h,2,CFG); x.status='in_stock'; self.assertEqual(event_for(x,h,3,CFG),'IN-STOCK LEAD')


class AceParserTests(unittest.TestCase):
    def test_html_at_cap(self):
        x=parse_html(priced_page('5500'),SOURCE,URL)[0]; self.assertEqual(event_for(x,{},1,CFG),'IN-STOCK LEAD')
    def test_html_over_cap(self):
        x=parse_html(priced_page('5999'),SOURCE,URL)[0]; self.assertIsNone(event_for(x,{},1,CFG))
    def test_sale_price_not_mrp(self):
        content='<p class="price"><del><span class="amount">5999</span></del><ins><span class="amount">5499</span></ins></p><p class="stock in-stock">In stock</p>'
        x=parse_html(page(content),SOURCE,URL)[0]; self.assertEqual(x.price,'5,499.00')
    def test_range_not_assigned_to_any_variant(self):
        content='<p class="price"><span class="amount">4500</span> - <span class="amount">5999</span></p><p class="stock in-stock">In stock</p>'
        x=parse_html(page(content),SOURCE,URL)[0]; self.assertIsNone(event_for(x,{},1,CFG))
    def test_shopify_new_used_and_buyback_isolation(self):
        data=dict(title=TITLE,available=True,variants=[
            dict(id=1,title='BUYBACK SELL',price=350000,available=True),
            dict(id=2,title='New',price=599900,available=True),
            dict(id=3,title='Used',price=530000,available=True)])
        xs=parse_shopify(data,SOURCE,URL); self.assertEqual(len(xs),2)
        self.assertIsNone(event_for(xs[0],{},1,CFG)); self.assertEqual(event_for(xs[1],{},1,CFG),'IN-STOCK LEAD')
    def test_shopify_new_unavailable_while_buyback_available(self):
        data=dict(title=TITLE,available=True,variants=[dict(id=1,title='BUYBACK',price=300000,available=True),dict(id=2,title='New',price=500000,available=False)])
        xs=parse_shopify(data,SOURCE,URL); self.assertEqual(len(xs),1); self.assertEqual(xs[0].status,'out_of_stock')
    def test_shopify_preorder_title_not_instock(self):
        data=dict(title=TITLE+' Pre Order',variants=[dict(id=1,title='New',price=500000,available=True)])
        self.assertEqual(parse_shopify(data,SOURCE,URL)[0].status,'backorder')
    def test_shopify_preorder_variant_not_instock(self):
        data=dict(title=TITLE,variants=[dict(id=1,title='Pre-order',price=500000,available=True)])
        self.assertEqual(parse_shopify(data,SOURCE,URL)[0].status,'backorder')
    def test_shopify_digital_disclosure(self):
        data=dict(title=TITLE,description='Code in box. No physical disc.',variants=[dict(id=1,title='New',price=500000,available=True)])
        self.assertEqual(parse_shopify(data,SOURCE,URL),[])
    def test_html_title_preorder(self): self.assertEqual(parse_html(priced_page(title=TITLE+' Pre Order'),SOURCE,URL)[0].status,'backorder')
    def test_html_outofstock_wins_over_preorder_title(self): self.assertEqual(parse_html(priced_page(stock='out-of-stock',title=TITLE+' Pre Order'),SOURCE,URL)[0].status,'out_of_stock')
    def test_old_preorder_slug_is_not_current_stock_signal(self):
        x=parse_html(priced_page(),SOURCE,URL.rstrip('/')+'-preorder')[0]; self.assertEqual(x.status,'in_stock')
    def test_generic_preorder_bonus_description_not_stock_signal(self):
        self.assertEqual(parse_html(priced_page(extra='<p>Preorder bonus: downloadable aircraft</p>'),SOURCE,URL)[0].status,'in_stock')
    def test_primary_preorder_button(self):
        content='<p class="price"><span class="amount">5000</span></p><button name="add-to-cart">Pre Order Now</button>'
        self.assertEqual(parse_html(page(content),SOURCE,URL)[0].status,'backorder')
    def test_woo_variant_preorder(self):
        variants=[dict(variation_id=1,attributes={'condition':'Preorder'},is_in_stock=True,is_purchasable=True,display_price=5000)]
        doc=page('<form class="variations_form" data-product_variations="'+html.escape(json.dumps(variants),quote=True)+'"></form>')
        self.assertEqual(parse_html(doc,SOURCE,URL)[0].status,'backorder')
    def test_code_only_in_body(self): self.assertEqual(parse_html(priced_page(extra='<p>No physical disc. Shared account.</p>'),SOURCE,URL),[])
    def test_case_only_in_body(self): self.assertEqual(parse_html(priced_page(extra='<p>Steelbook only. Game disc is not included.</p>'),SOURCE,URL),[])
    def test_foreign_schema_currency_kept(self):
        data={'@type':'Product','name':TITLE,'offers':{'@type':'Offer','price':45,'priceCurrency':'USD','availability':'https://schema.org/InStock'}}
        x=parse_html(page()+'<script type="application/ld+json">'+json.dumps(data)+'</script>',SOURCE,URL)[0]
        self.assertEqual(x.currency,'USD'); self.assertIsNone(event_for(x,{},1,CFG))
    def test_recommendations_not_match(self): self.assertEqual(parse_html(page('<div class="related">'+TITLE+'</div>',title='Ace Combat 7 PS4'),SOURCE,URL),[])


class AceDiscoveryTests(unittest.TestCase):
    def test_hints(self):
        for text in ['ace-combat-8-ps5','AceCombat8','wings-of-theve','Ace Combat VIII']:
            with self.subTest(text=text): self.assertTrue(discovery_hint(text,'acecombat8'))
    def test_old_hints_rejected(self):
        for text in ['ace-combat-7','onimusha','pragmata','elden ring sote']:
            with self.subTest(text=text): self.assertFalse(discovery_hint(text,'acecombat8'))
    def test_html_discovery_specific(self):
        doc='<a href="'+URL+'">'+TITLE+'</a><a href="/product/ace-combat-7-ps4">Ace Combat 7 PS4</a>'
        links,_=discover_html(doc,SOURCE['base'],'acecombat8'); self.assertEqual(links,[canonical_url(URL)])
    def test_sitemap_discovery_specific(self):
        doc='<urlset><url><loc>'+URL+'</loc></url><url><loc>https://store.example/product/onimusha-ps5</loc></url></urlset>'
        _,links=sitemap_links(doc,SOURCE['base'],target='acecombat8'); self.assertEqual(links,[URL])
    def test_real_scan_source_target_propagation(self):
        class Client:
            def __init__(self,*args): self.calls=0
            def get(self,url): self.calls+=1; return priced_page()
        items,report=scan_source(SOURCE,{},CFG,time.time(),client_factory=Client)
        self.assertEqual(len(items),1); self.assertEqual(report['product_pages'],1)


class AceIntegrationTests(unittest.TestCase):
    def invoke(self,store,notify,item=None,force=False,dry=False):
        with patch('sote.engine.scan_source',return_value=([item or listing()],REPORT)), patch('sote.engine.write_run_summary',return_value='offline acecombat8 test'), redirect_stdout(io.StringIO()):
            return run_scan(CFG,store,notify,force_health=force,dry_run=dry)
    def test_config_target_and_5500(self):
        cfg=read_config(str(ROOT/'config.json')); self.assertEqual(cfg['target'],'acecombat8'); self.assertEqual(cfg['max_price_inr'],5500)
        self.assertFalse(cfg['daily_health']); self.assertFalse(cfg['reddit']['enabled']); self.assertFalse(cfg['alert_possible'])
        self.assertTrue(all(s['target']=='acecombat8' for s in cfg['sources']))
    def test_no_old_active_seed_or_query(self):
        cfg=read_config(str(ROOT/'config.json'))
        for source in cfg['sources']:
            for url in source.get('products',[])+source.get('catalogues',[]):
                self.assertFalse(any(w in url.lower() for w in ['onimusha','pragmata','erdtree','elden']))
    def test_seed_sources(self):
        cfg=read_config(str(ROOT/'config.json'))
        self.assertEqual({s['id'] for s in cfg['sources'] if s.get('products')},{'gamebuy','dtzone','mcube','psx','playhq'})
    def test_external_reddit_not_enabled_for_new_target(self):
        cfg=copy.deepcopy(CFG); cfg['reddit']['enabled']=True
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'config.json'; f.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError): read_config(str(f))
    def test_scanner_marker(self): self.assertEqual(SCANNER_REVISION,'acecombat8-5500-1')
    def test_http_user_agent(self): self.assertEqual(StoreClient(SOURCE,{},CFG).agent,'AceCombat8StockWatcher')
    def test_automatic_no_health(self):
        notify=Mock(); self.assertEqual(self.invoke(MemoryStore(),notify),0); notify.send.assert_not_called(); self.assertEqual(notify.listing.call_count,1)
    def test_over_cap_no_purchase_alert_or_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify,listing('5999')); notify.send.assert_not_called(); notify.listing.assert_not_called()
    def test_manual_status_sends_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify,force=True)
        self.assertEqual(notify.send.call_args.args[0],'HEALTH: Ace Combat 8: Wings of Theve tracker')
    def test_migration_resets_old_target_but_not_cooldown(self):
        st=empty_state(); st['target']='onimusha'; st['listings']={'old':{'last_seen':time.time()}}
        st['sources']={'demo':{'known':{'https://store.example/product/onimusha':1},'cooldown_until':99999999999}}
        store=MemoryStore(st); self.invoke(store,Mock()); self.assertEqual(store.state['target'],'acecombat8')
        self.assertNotIn('old',store.state['listings']); self.assertNotIn('known',store.state['sources']['demo'])
        self.assertEqual(store.state['sources']['demo']['cooldown_until'],99999999999)
    def test_second_run_not_duplicate(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify); self.invoke(store,notify); self.assertEqual(notify.listing.call_count,1)
    def test_dry_run_does_not_mutate_or_notify(self):
        store=MemoryStore(); before=copy.deepcopy(store.state); notify=Mock(); self.invoke(store,notify,dry=True)
        self.assertEqual(store.state,before); notify.send.assert_not_called(); notify.listing.assert_not_called()
    def test_delivery_failure_retried(self):
        store=MemoryStore(); notify=Mock(); notify.listing.side_effect=NotificationError('synthetic error')
        self.assertEqual(self.invoke(store,notify),1); notify.listing.side_effect=None
        self.assertEqual(self.invoke(store,notify),0); self.assertEqual(notify.listing.call_count,2)
    def test_summary_5500_and_brand(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}):
            try:
                os.chdir(td); result=write_run_summary([REPORT],[listing('5999')],[],CFG)
            finally: os.chdir(old)
        self.assertIn('Ace Combat 8: Wings of Theve tracker run',result)
        self.assertIn('INR 5500',result); self.assertIn('Daily health: off',result); self.assertIn('above INR 5,500',result)
    def test_discord_branding_and_limit(self):
        d=Discord('https://discord.com/api/webhooks/123456/UNIT_TEST_NOT_A_REAL_TOKEN',target='acecombat8',max_price_inr=5500)
        response=Mock(status_code=200); response.json.return_value={'id':'123'}; d.session.post=Mock(return_value=response)
        d.listing(listing(),'IN-STOCK LEAD'); body=d.session.post.call_args.kwargs['json']
        self.assertEqual(body['username'],'Ace Combat 8: Wings of Theve Watcher'); self.assertEqual(body['allowed_mentions'],{'parse':[]})
        self.assertIn('INR 5500',json.dumps(body)); self.assertNotIn('Onimusha',json.dumps(body))
    def test_cli_test_payload_no_actual_webhook(self):
        with patch.object(tracker.sys,'argv',['tracker.py','--mode','test','--config',str(ROOT/'config.json')]), patch.object(tracker,'Discord') as cls, redirect_stdout(io.StringIO()):
            self.assertEqual(tracker.main(),0)
        title,text=cls.return_value.send.call_args.args
        self.assertEqual(title,'TEST: Ace Combat 8: Wings of Theve tracker connected')
        self.assertIn('INR 5500',text); self.assertIn('Daily health messages: off',text)
    def test_public_config_contains_no_personal_credentials(self):
        cfg=json.loads((ROOT/'config.json').read_text()); self.assertNotIn('webhook',json.dumps(cfg).lower())


if __name__=='__main__': unittest.main()
