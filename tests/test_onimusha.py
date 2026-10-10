"""Offline tests of the Onimusha switch. Fixtures are NOT real stock claims."""
import copy
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from sote.budget import budget_decision
from sote.engine import (SCANNER_REVISION, acknowledge, event_for, read_config,
                         run_scan, scan_source, write_run_summary)
from sote.http import StoreClient
from sote.model import Listing, discovery_hint, match_product, target_name
from sote.notify import Discord, NotificationError
from sote.parsers import discover_html, parse_html, parse_shopify, sitemap_links
from sote.storage import empty_state

TITLE = 'Onimusha: Way of the Sword PS5'
URL = 'https://store.example/product/onimusha-way-of-the-sword-ps5/'
SOURCE = {'id':'demo','name':'Demo','base':'https://store.example',
          'products':[URL],'target':'onimusha','currency':'INR'}
CFG = {'target':'onimusha','max_price_inr':4000,'daily_health':False,
       'alert_possible':False,'sources':[SOURCE],'reddit':{'enabled':False}}
REPORT = {'name':'Demo','product_pages':1,'discovery_pages':0,'errors':[]}


def listing(price='3,900.00', **kwargs):
    data = dict(source='Demo',title=TITLE,url=URL,status='in_stock',price=price)
    data.update(kwargs)
    return Listing(**data)


def page(content='', title=TITLE):
    return '<div class="product"><div class="summary"><h1 class="product_title">'+title+'</h1>'+content+'</div></div>'


class MemoryStore:
    def __init__(self,state=None): self.state=copy.deepcopy(state or empty_state())
    def load(self): return copy.deepcopy(self.state)
    def save(self,state): self.state=copy.deepcopy(state)


class OnimushaMatchingTests(unittest.TestCase):
    def check(self, text, expected='exact', url=URL):
        self.assertEqual(match_product(text,url,'onimusha'),expected)
    def test_full_title(self): self.check(TITLE)
    def test_mixed_case_and_punctuation(self): self.check('ONIMUSHA - WAY OF THE SWORD (PlayStation 5)')
    def test_optional_the(self): self.check('Onimusha Way of Sword PS5')
    def test_lenticular_edition(self): self.check('Onimusha Way of the Sword PS5 Lenticular Edition')
    def test_steelbook_edition_with_game(self): self.check(TITLE+' Steelbook Edition')
    def test_disc_only_accepted(self): self.check(TITLE+' Disc Only')
    def test_new_and_used(self):
        for condition in ['New','Factory Sealed','Pre-Owned','Used','Second Hand']:
            with self.subTest(condition=condition): self.check(TITLE+' '+condition)
    def test_abbreviated_wots_with_brand(self): self.check('Onimusha WOTS PS5')
    def test_generic_name_stays_possible(self): self.check('Onimusha PS5','possible','https://store.example/product/onimusha-ps5')
    def test_specific_url_disambiguates(self): self.check('Onimusha PS5')
    def test_platform_unknown_stays_possible(self): self.check('Onimusha Way of the Sword','possible','https://store.example/product/game')
    def test_url_supplies_platform(self): self.check('Onimusha Way of the Sword')
    def test_wrong_primary_title_not_rescued(self): self.check('Pragmata PS5','reject')
    def test_old_sote_rejected(self): self.check('Elden Ring Shadow of the Erdtree PS5','reject')
    def test_other_onimusha_titles_rejected(self):
        for name in ['Warlords','2 Samurai\'s Destiny','Samurai Destiny','3 Demon Siege',
                     'Dawn of Dreams','Blade Warriors','Tactics','II','III','IV']:
            with self.subTest(name=name): self.check('Onimusha '+name+' PS5','reject')
    def test_wrong_platforms(self):
        for platform in ['PS4','PS2','PlayStation 4','Xbox Series X','PC','Switch 2']:
            with self.subTest(platform=platform): self.check('Onimusha Way of the Sword '+platform,'reject')
    def test_mixed_platform_ambiguous(self): self.check(TITLE+' Xbox','possible')
    def test_only_series_word_is_not_a_match(self): self.check('Onimushaland Way of the Sword PS5','reject')
    def test_hitech_steel_book_only_title(self): self.check('Onimusha Way of the Sword - Steel Book Only','reject')
    def test_non_disc_products(self):
        for suffix in ['Steelbook Only','Empty Case','Case Only','No Disc','Game disc is not included',
                       'Without the disc','Digital','Shared Account','Rental','Steam key','Code in the box',
                       'DLC','Preorder bonus','Demo','Soundtrack','Artbook','Statue','Deposit','Booking','WTB']:
            with self.subTest(suffix=suffix): self.check(TITLE+' '+suffix,'reject')
    def test_buyback_not_purchase(self): self.check(TITLE+' BUYBACK (SELL)','reject')


class OnimushaBudgetEventTests(unittest.TestCase):
    def test_at_4000_allowed(self): self.assertEqual(event_for(listing('4000'),{},1,CFG),'IN-STOCK LEAD')
    def test_4000_01_suppressed(self): self.assertIsNone(event_for(listing('4000.01'),{},1,CFG))
    def test_above_cap_suppressed(self): self.assertIsNone(event_for(listing('5299'),{},1,CFG))
    def test_unknown_price_suppressed(self): self.assertIsNone(event_for(listing('Not verified'),{},1,CFG))
    def test_foreign_currency_suppressed(self): self.assertIsNone(event_for(listing('30',currency='EUR'),{},1,CFG))
    def test_nonprices_suppressed(self):
        for price in ['0','-100','NaN','Infinity','3.9k','3999-4999','3999 with coupon']:
            with self.subTest(price=price): self.assertIsNone(event_for(listing(price),{},1,CFG))
    def test_nonavailable_suppressed(self):
        for status in ['out_of_stock','backorder','unknown']:
            with self.subTest(status=status): self.assertIsNone(event_for(listing(status=status),{},1,CFG))
    def test_old_game_not_added_to_history(self):
        history={}
        self.assertIsNone(event_for(listing(title='Pragmata PS5'),history,1,CFG))
        self.assertEqual(history,{})
    def test_ambiguous_title_not_promoted_by_listing_default(self):
        item=listing(title='Onimusha PS5',url='https://store.example/product/onimusha-ps5')
        self.assertIsNone(event_for(item,{},1,CFG)); self.assertEqual(item.match,'possible')
    def test_parser_possible_not_promoted(self): self.assertIsNone(event_for(listing(match='possible'),{},1,CFG))
    def test_deduplicate(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        self.assertIsNone(event_for(x,h,2,CFG))
    def test_price_drop_without_restock(self):
        h={}; x=listing('4500'); self.assertIsNone(event_for(x,h,1,CFG))
        x.price='4000'; self.assertEqual(event_for(x,h,2,CFG),'IN-STOCK LEAD')
    def test_price_reenters_cap(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.price='4100'; event_for(x,h,2,CFG)
        x.price='3999'; self.assertEqual(event_for(x,h,3,CFG),'IN-STOCK LEAD')
    def test_restock(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.status='out_of_stock'; event_for(x,h,2,CFG)
        x.status='in_stock'; self.assertEqual(event_for(x,h,3,CFG),'IN-STOCK LEAD')
    def test_unknown_price_does_not_rearm(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,'IN-STOCK LEAD')
        x.price='Not verified'; event_for(x,h,2,CFG)
        x.price='3900'; self.assertIsNone(event_for(x,h,3,CFG))


class OnimushaParserTests(unittest.TestCase):
    def test_current_sale_price_only(self):
        content='<p class="price"><del><span class="amount">5499</span></del><ins><span class="amount">3999</span></ins></p><p class="stock in-stock">In stock</p>'
        item=parse_html(page(content),SOURCE,URL)[0]
        self.assertEqual((item.status,item.price),('in_stock','3,999.00'))
    def test_out_of_stock_over_generic_preorder(self):
        content='<p class="stock out-of-stock">Out of stock</p><p>Preorder shipping policy</p><p class="price"><span class="amount">3900</span></p>'
        self.assertEqual(parse_html(page(content),SOURCE,URL)[0].status,'out_of_stock')
    def test_structured_offer_not_recommendation(self):
        schema='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':TITLE,'offers':{'@type':'Offer','price':3900,'priceCurrency':'INR','availability':'https://schema.org/InStock'}})+'</script>'
        item=parse_html(page()+schema,SOURCE,URL)[0]
        self.assertEqual(item.price,'3,900.00'); self.assertEqual(item.status,'in_stock')
    def test_related_match_cannot_replace_main_game(self):
        self.assertEqual(parse_html(page('<div class="related">'+TITLE+'</div>',title='Pragmata PS5'),SOURCE,URL),[])
    def test_case_only_claim_in_purchase_scope(self):
        self.assertEqual(parse_html(page('<p>STEELBOOK ONLY - GAME DISC IS NOT INCLUDED.</p>'),SOURCE,URL),[])
    def test_shared_account_in_purchase_scope(self):
        self.assertEqual(parse_html(page('<p>Shared account, no physical disc</p>'),SOURCE,URL),[])
    def test_code_in_the_box_in_purchase_scope(self):
        self.assertEqual(parse_html(page('<p>Code in the box</p>'),SOURCE,URL),[])
    def test_ambiguous_price_range(self):
        content='<p class="price"><span class="amount">3999</span> - <span class="amount">4999</span></p><p class="stock in-stock">In stock</p>'
        self.assertIsNone(event_for(parse_html(page(content),SOURCE,URL)[0],{},1,CFG))
    def test_shopify_filters_variants(self):
        data={'title':TITLE,'variants':[
            {'id':1,'title':'BUYBACK (SELL)','available':True,'price':200000},
            {'id':2,'title':'Used','available':True,'price':399900},
            {'id':3,'title':'New','available':True,'price':549900},
            {'id':4,'title':'Digital','available':True,'price':100000},
            {'id':5,'title':'Steel Book Only','available':True,'price':100000}]}
        items=parse_shopify(data,SOURCE,URL)
        self.assertEqual(len(items),2)
        self.assertEqual(event_for(items[0],{},1,CFG),'IN-STOCK LEAD')
        self.assertIsNone(event_for(items[1],{},1,CFG))
    def test_shopify_does_not_use_aggregate_available(self):
        data={'title':TITLE,'available':True,'variants':[{'id':1,'title':'Used','available':False,'price':390000}]}
        self.assertEqual(parse_shopify(data,SOURCE,URL)[0].status,'out_of_stock')
    def test_shopify_preorder_not_ready_stock(self):
        data={'title':TITLE,'variants':[{'id':1,'title':'Pre-Order','available':True,'price':390000}]}
        item=parse_shopify(data,SOURCE,URL)[0]
        self.assertEqual(item.status,'backorder'); self.assertIsNone(event_for(item,{},1,CFG))
    def test_shopify_shipping_false_excluded(self):
        data={'title':TITLE,'variants':[{'id':1,'title':'Used','available':True,'price':390000,'requires_shipping':False}]}
        self.assertEqual(parse_shopify(data,SOURCE,URL),[])
    def test_woo_variants_individually_priced(self):
        variants=[{'variation_id':1,'attributes':{'condition':'Used'},'is_in_stock':True,'display_price':3900},
                  {'variation_id':2,'attributes':{'condition':'New'},'is_in_stock':True,'display_price':5499}]
        content='<form class="variations_form" data-product_variations="'+html.escape(json.dumps(variants),quote=True)+'"></form>'
        items=parse_html(page(content),SOURCE,URL)
        self.assertEqual([x.price for x in items],['3,900.00','5,499.00'])
    def test_catalogue_discovers_onimusha_not_pragmata(self):
        body='<a href="'+URL+'">'+TITLE+'</a><a href="/product/pragmata-ps5/">Pragmata PS5</a>'
        urls,_=discover_html(body,URL,'onimusha')
        self.assertEqual(urls,[URL.rstrip('/')])
    def test_sitemap_discovers_new_title(self):
        xml='<urlset><url><loc>'+URL+'</loc></url><url><loc>https://store.example/product/pragmata-ps5/</loc></url></urlset>'
        _,urls=sitemap_links(xml,SOURCE['base'],target='onimusha'); self.assertEqual(urls,[URL])
    def test_sitemap_opaque_with_title(self):
        xml='<urlset><url><loc>https://store.example/product/1234</loc><title>'+TITLE+'</title></url></urlset>'
        _,urls=sitemap_links(xml,SOURCE['base'],target='onimusha'); self.assertEqual(len(urls),1)
    def test_sitemap_opaque_without_title_not_invented(self):
        xml='<urlset><url><loc>https://store.example/product/1234</loc></url></urlset>'
        _,urls=sitemap_links(xml,SOURCE['base'],target='onimusha'); self.assertEqual(urls,[])
    def test_discovery_hint_broader_than_purchase(self):
        self.assertTrue(discovery_hint('Onimusha Warlords','onimusha'))
        self.assertFalse(discovery_hint('Pragmata','onimusha'))
        self.assertEqual(match_product('Onimusha Warlords PS4',URL,'onimusha'),'reject')
    def test_scan_source_propagates_target(self):
        class Client:
            def __init__(self,*a): self.calls=0
            def get(self,url):
                self.calls+=1
                return page('<p class="stock in-stock">In stock</p><p class="price"><span class="amount">3900</span></p>')
        items,report=scan_source(SOURCE,{},CFG,time.time(),client_factory=Client)
        self.assertEqual(items[0].title,TITLE); self.assertEqual(report['product_pages'],1)


class OnimushaIntegrationTests(unittest.TestCase):
    def invoke(self,store,notifier,item=None,force=False,dry=False):
        with patch('sote.engine.scan_source',return_value=([item or listing()],REPORT)), patch('sote.engine.write_run_summary',return_value='offline Onimusha test'):
            return run_scan(CFG,store,notifier,force_health=force,dry_run=dry)
    def test_normal_scan_does_not_send_daily_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify)
        notify.send.assert_not_called(); self.assertEqual(notify.listing.call_count,1)
    def test_manual_status_sends_one_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify,force=True)
        self.assertEqual(notify.send.call_count,1)
        self.assertEqual(notify.send.call_args.args[0],'HEALTH: Onimusha: Way of the Sword tracker')
    def test_no_purchase_above_cap_and_no_daily(self):
        notify=Mock(); self.invoke(MemoryStore(),notify,listing('5499'))
        notify.send.assert_not_called(); notify.listing.assert_not_called()
    def test_migration_from_pragmata_preserves_cooldown(self):
        st=empty_state(); st['target']='pragmata'
        st['sources']={'demo':{'known':{'https://store.example/product/pragmata-ps5':1},'cooldown_until':99999999999}}
        st['listings']={'old':{'last_seen':time.time()}}
        store=MemoryStore(st); self.invoke(store,Mock())
        self.assertEqual(store.state['target'],'onimusha')
        self.assertNotIn('old',store.state['listings'])
        self.assertNotIn('known',store.state['sources']['demo'])
        self.assertEqual(store.state['sources']['demo']['cooldown_until'],99999999999)
    def test_migration_from_original_sote(self):
        store=MemoryStore(); self.invoke(store,Mock()); self.assertEqual(store.state['target'],'onimusha')
    def test_history_not_reset_each_scan(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify); self.invoke(store,notify)
        self.assertEqual(notify.listing.call_count,1)
    def test_failed_delivery_retries(self):
        store=MemoryStore(); notify=Mock(); notify.listing.side_effect=NotificationError('offline test')
        self.assertEqual(self.invoke(store,notify),1)
        notify.listing.side_effect=None
        self.assertEqual(self.invoke(store,notify),0); self.assertEqual(notify.listing.call_count,2)
    def test_dry_run_does_not_save_or_send(self):
        store=MemoryStore(); before=copy.deepcopy(store.state); notify=Mock()
        self.invoke(store,notify,dry=True)
        self.assertEqual(before,store.state); notify.send.assert_not_called(); notify.listing.assert_not_called()
    def test_config_target_and_budget(self):
        cfg=read_config(str(Path(__file__).parent/'fixtures/onimusha_config.json'))
        self.assertEqual(cfg['target'],'onimusha'); self.assertIsNone(cfg['max_price_inr'])
        self.assertFalse(cfg['daily_health']); self.assertFalse(cfg['alert_possible']); self.assertFalse(cfg['reddit']['enabled'])
        for source in cfg['sources']:
            self.assertEqual(source['target'],'onimusha')
            for url in source.get('products',[])+source.get('catalogues',[]):
                for old in ['pragmata','elden','erdtree']:
                    self.assertNotIn(old,url)
    def test_reddit_direct_module_stays_disallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=copy.deepcopy(CFG); cfg['reddit']['enabled']=True
            path=Path(directory)/'config.json'; path.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError): read_config(str(path))
    def test_revision_marker(self): self.assertEqual(SCANNER_REVISION,'acecombat8-5500-1')
    def test_summary_branding_budget_and_off(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}):
            try:
                os.chdir(directory); text=write_run_summary([REPORT],[listing('4050')],[],CFG)
            finally: os.chdir(old)
        self.assertIn('# Onimusha: Way of the Sword tracker run',text)
        self.assertIn('Daily health: off',text); self.assertIn('above INR 4,000',text)
    def test_discord_payload_branding_and_mentions(self):
        notifier=Discord('https://discord.com/api/webhooks/123456/secret',target='onimusha',max_price_inr=4000)
        response=Mock(status_code=200); response.json.return_value={'id':'123'}
        notifier.session.post=Mock(return_value=response)
        notifier.listing(listing(),'IN-STOCK LEAD')
        payload=notifier.session.post.call_args.kwargs['json']
        self.assertEqual(payload['username'],'Onimusha: Way of the Sword Watcher')
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})
        self.assertNotIn('Pragmata',json.dumps(payload)); self.assertNotIn('SOTE',json.dumps(payload))
    def test_http_user_agent(self):
        client=StoreClient(SOURCE,{},CFG)
        self.assertEqual(client.agent,'OnimushaStockWatcher')
    def test_demo_uses_selected_target_without_network(self):
        repo=Path(__file__).resolve().parents[1]
        p=subprocess.run([sys.executable,str(repo/'tracker.py'),'--mode','demo','--config',str(repo/'tests/fixtures/onimusha_config.json')],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['title'],TITLE)


if __name__=='__main__': unittest.main()
