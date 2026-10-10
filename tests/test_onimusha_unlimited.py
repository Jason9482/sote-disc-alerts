"""Uncapped Onimusha acceptance and integration tests. All data is synthetic."""
import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from sote.budget import budget_decision, price_limit_label
from sote.engine import acknowledge, event_for, health_text, read_config, run_scan, write_run_summary
from sote.model import Listing
from sote.notify import Discord, safe_text
from sote.parsers import parse_html, parse_shopify
from sote.storage import empty_state
import tracker

TITLE = 'Onimusha: Way of the Sword PS5'
URL = 'https://store.example/product/onimusha-way-of-the-sword-ps5/'
SOURCE = {'id':'demo','name':'Demo','base':'https://store.example',
          'products':[URL],'target':'onimusha','currency':'INR'}
CFG = {'target':'onimusha','max_price_inr':None,'daily_health':False,
       'alert_possible':False,'sources':[SOURCE],'reddit':{'enabled':False}}
REPORT = {'name':'Demo','product_pages':1,'discovery_pages':0,'errors':[]}
REPO = Path(__file__).resolve().parents[1]


def listing(price='5499', **kw):
    data=dict(source='Demo',title=TITLE,url=URL,price=price,status='in_stock')
    data.update(kw)
    return Listing(**data)


class MemoryStore:
    def __init__(self,state=None): self.state=copy.deepcopy(state or empty_state())
    def load(self): return copy.deepcopy(self.state)
    def save(self,state): self.state=copy.deepcopy(state)


class UnlimitedPriceTests(unittest.TestCase):
    def test_config_is_onimusha_unlimited(self):
        cfg=read_config(str(REPO/'tests/fixtures/onimusha_config.json'))
        self.assertEqual(cfg['target'],'onimusha')
        self.assertIsNone(cfg['max_price_inr'])
        self.assertFalse(cfg['daily_health'])
        self.assertFalse(cfg['reddit']['enabled'])
    def test_config_uses_real_json_null_not_text(self):
        text=(REPO/'tests/fixtures/onimusha_config.json').read_text()
        self.assertIn('"max_price_inr": null',text)
        self.assertNotIn('"max_price_inr": "null"',text)
    def test_above_old_4000_threshold_allowed(self):
        for price in ['4000.01','5299','5499','7499','15000','99,99,999.99']:
            with self.subTest(price=price):
                self.assertEqual(event_for(listing(price),{},1,CFG),'IN-STOCK LEAD')
    def test_unknown_price_does_not_hide_stock(self):
        self.assertEqual(event_for(listing('Not verified'),{},1,CFG),'IN-STOCK LEAD')
    def test_foreign_currency_not_a_hidden_price_limit(self):
        self.assertEqual(event_for(listing('100',currency='USD'),{},1,CFG),'IN-STOCK LEAD')
    def test_cap_omitted_is_unlimited_too(self):
        cfg=copy.deepcopy(CFG); del cfg['max_price_inr']
        self.assertEqual(event_for(listing('15000'),{},1,cfg),'IN-STOCK LEAD')
    def test_no_maximum_number_substitution(self):
        item=listing('1000000000')
        self.assertTrue(budget_decision(item,CFG)[0])
    def test_out_of_stock_stays_suppressed(self):
        self.assertIsNone(event_for(listing(status='out_of_stock'),{},1,CFG))
    def test_backorder_stays_suppressed(self):
        self.assertIsNone(event_for(listing(status='backorder'),{},1,CFG))
    def test_unknown_stock_stays_suppressed(self):
        self.assertIsNone(event_for(listing(status='unknown'),{},1,CFG))
    def test_old_target_stays_suppressed(self):
        self.assertIsNone(event_for(listing(title='Pragmata PS5'),{},1,CFG))
    def test_warlords_stays_suppressed(self):
        self.assertIsNone(event_for(listing(title='Onimusha Warlords PS4'),{},1,CFG))
    def test_steelbook_only_stays_suppressed(self):
        self.assertIsNone(event_for(listing(title=TITLE+' SteelBook Only'),{},1,CFG))
    def test_digital_account_stays_suppressed(self):
        self.assertIsNone(event_for(listing(title=TITLE+' Digital Account'),{},1,CFG))
    def test_wrong_platform_stays_suppressed(self):
        self.assertIsNone(event_for(listing(title='Onimusha Way of the Sword Xbox'),{},1,CFG))
    def test_buyback_stays_suppressed(self):
        self.assertIsNone(event_for(listing(variant='BUYBACK SELL'),{},1,CFG))
    def test_same_instock_offer_not_repeated(self):
        item=listing(); history={}
        self.assertEqual(event_for(item,history,1,CFG),'IN-STOCK LEAD')
        acknowledge(item,history,'IN-STOCK LEAD')
        self.assertIsNone(event_for(item,history,2,CFG))
    def test_price_change_alone_does_not_repeat_unlimited_alert(self):
        item=listing(); history={}
        event_for(item,history,1,CFG); acknowledge(item,history,'IN-STOCK LEAD')
        item.price='3999'; self.assertIsNone(event_for(item,history,2,CFG))
        item.price='7499'; self.assertIsNone(event_for(item,history,3,CFG))
    def test_restock_still_notifies(self):
        item=listing(); history={}
        event_for(item,history,1,CFG); acknowledge(item,history,'IN-STOCK LEAD')
        item.status='out_of_stock'; event_for(item,history,2,CFG)
        item.status='in_stock'; self.assertEqual(event_for(item,history,3,CFG),'IN-STOCK LEAD')
    def test_removing_existing_cap_releases_unalerted_offer(self):
        item=listing(); history={}; capped=dict(CFG,max_price_inr=4000)
        self.assertIsNone(event_for(item,history,1,capped))
        self.assertEqual(event_for(item,history,2,CFG),'IN-STOCK LEAD')
    def test_both_new_and_used_can_alert(self):
        data={'title':TITLE,'variants':[
            {'id':1,'title':'Used','available':True,'price':450000},
            {'id':2,'title':'New','available':True,'price':549900},
            {'id':3,'title':'BUYBACK','available':True,'price':300000}]}
        items=parse_shopify(data,SOURCE,URL)
        self.assertEqual(len(items),2)
        self.assertTrue(all(event_for(x,{},1,CFG)=='IN-STOCK LEAD' for x in items))
    def test_html_high_price_allowed_after_real_parser(self):
        doc='<div class="product"><div class="summary"><h1>'+TITLE+'</h1><p class="price"><span class="amount">5499</span></p><p class="stock in-stock">In stock</p></div></div>'
        item=parse_html(doc,SOURCE,URL)[0]
        self.assertEqual(item.price,'5,499.00')
        self.assertEqual(event_for(item,{},1,CFG),'IN-STOCK LEAD')
    def test_unlimited_label(self): self.assertEqual(price_limit_label(None),'Unlimited (no price cap)')
    def test_capped_label_still_supported(self): self.assertEqual(price_limit_label(4000),'INR 4000')


class UnlimitedIntegrationTests(unittest.TestCase):
    def invoke(self,store,notify,force=False):
        with patch('sote.engine.scan_source',return_value=([listing()],REPORT)), patch('sote.engine.write_run_summary',return_value='offline unlimited test'), redirect_stdout(io.StringIO()):
            return run_scan(CFG,store,notify,force_health=force)
    def test_automatic_scan_sends_expensive_stock_not_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify)
        self.assertEqual(notify.listing.call_count,1); notify.send.assert_not_called()
    def test_manual_status_still_sends_health(self):
        notify=Mock(); self.invoke(MemoryStore(),notify,True)
        self.assertEqual(notify.listing.call_count,1); self.assertEqual(notify.send.call_count,1)
        self.assertIn('Unlimited',notify.send.call_args.args[1])
    def test_pragmata_state_migrated(self):
        state=empty_state(); state['target']='pragmata'
        state['listings']={'old':{'last_seen':time.time()}}
        state['sources']={'demo':{'known':{'https://store.example/pragmata':1},'cooldown_until':99999999999}}
        store=MemoryStore(state); self.invoke(store,Mock())
        self.assertEqual(store.state['target'],'onimusha')
        self.assertNotIn('old',store.state['listings'])
        self.assertNotIn('known',store.state['sources']['demo'])
        self.assertEqual(store.state['sources']['demo']['cooldown_until'],99999999999)
    def test_health_text_no_none_or_old_cap(self):
        text=health_text([REPORT],empty_state(),'external',CFG)
        self.assertIn('Price limit: Unlimited (no price cap)',text)
        self.assertNotIn('INR None',text); self.assertNotIn('4000',text)
    def test_summary_no_none_or_old_cap(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}):
            try:
                os.chdir(temp); text=write_run_summary([REPORT],[listing()],[],CFG)
            finally: os.chdir(old)
        self.assertIn('Price limit: Unlimited (no price cap)',text)
        self.assertIn('Daily health: off',text)
        self.assertNotIn('INR None',text); self.assertNotIn('above INR',text)
    def test_discord_fields_say_unlimited(self):
        d=Discord('https://discord.com/api/webhooks/123456/secret',target='onimusha',max_price_inr=None)
        response=Mock(status_code=200); response.json.return_value={'id':'123'}
        d.session.post=Mock(return_value=response); d.listing(listing(),'IN-STOCK LEAD')
        payload=d.session.post.call_args.kwargs['json']
        field=next(f for f in payload['embeds'][0]['fields'] if f['name']=='Price limit')
        self.assertIn(safe_text('Unlimited (no price cap)'),field['value'])
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})
    def test_cli_test_reports_unlimited(self):
        with patch.object(tracker.sys,'argv',['tracker.py','--mode','test','--config',str(REPO/'tests/fixtures/onimusha_config.json')]), patch.object(tracker,'Discord') as cls, redirect_stdout(io.StringIO()):
            self.assertEqual(tracker.main(),0)
            text=cls.return_value.send.call_args.args[1]
            self.assertIn('Price limit: Unlimited (no price cap)',text)
            self.assertIn('Daily health messages: off',text)
            self.assertNotIn('INR None',text)
    def test_no_filter_change_required_in_discord_secret(self):
        cfg=json.loads((REPO/'tests/fixtures/onimusha_config.json').read_text())
        self.assertNotIn('webhook',json.dumps(cfg).lower())
    def test_three_existing_seed_sources_have_new_target_only(self):
        cfg=read_config(str(REPO/'tests/fixtures/onimusha_config.json'))
        seeds={s['id']:s['products'] for s in cfg['sources'] if s.get('products')}
        self.assertEqual(set(seeds),{'gamebuy','flipkart','sheenu'})
        for urls in seeds.values():
            for url in urls:
                self.assertIn('onimusha',url)
                self.assertNotIn('pragmata',url)


if __name__=='__main__': unittest.main()
