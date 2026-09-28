"""Offline regression tests for the actual Pragmata switch and inclusive price cap."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from sote.budget import budget_decision, price_number
from sote.model import Listing, match_product, discovery_hint
from sote.parsers import parse_html, parse_shopify, discover_html, sitemap_links
from sote.engine import event_for, acknowledge, read_config, run_scan, scan_source, write_run_summary
from sote.storage import empty_state
from sote.notify import Discord

URL = "https://store.example/product/pragmata-ps5/"
SOURCE = {"id":"demo", "name":"Demo", "base":"https://store.example", "products":[URL], "target":"pragmata"}
CFG = {"target":"pragmata", "sources":[SOURCE], "max_price_inr":4000, "daily_health":False,
       "alert_possible":False, "reddit":{"enabled":False}}
REPORT = {"name":"Demo", "product_pages":1, "discovery_pages":0, "errors":[]}

def listing(price="3,900.00", **kwargs):
    data = dict(source="Demo", title="Pragmata PS5", url=URL, status="in_stock", price=price)
    data.update(kwargs)
    return Listing(**data)

def page(content, title="Pragmata PS5", schema=""):
    return f'<div class="product"><div class="summary"><h1 class="product_title">{title}</h1>{content}</div></div>{schema}'

class MemoryStore:
    def __init__(self, state=None): self.state=copy.deepcopy(state or empty_state())
    def load(self): return copy.deepcopy(self.state)
    def save(self, value): self.state=copy.deepcopy(value)

class PragmataMatcherTests(unittest.TestCase):
    def test_normal_ps5(self): self.assertEqual(match_product("PRAGMATA PS5",URL,"pragmata"),"exact")
    def test_used(self): self.assertEqual(match_product("Pragmata - PlayStation 5 Pre-Owned",URL,"pragmata"),"exact")
    def test_new(self): self.assertEqual(match_product("Pragmata PS5 Sealed",URL,"pragmata"),"exact")
    def test_disc_only_is_accepted(self): self.assertEqual(match_product("Pragmata PS5 disc only",URL,"pragmata"),"exact")
    def test_old_game_rejected(self): self.assertEqual(match_product("Elden Ring Shadow of the Erdtree Edition PS5",URL,"pragmata"),"reject")
    def test_word_boundary(self): self.assertEqual(match_product("Pragmatastic PS5",URL,"pragmata"),"reject")
    def test_wrong_platforms(self):
        for text in ["Pragmata PC", "Pragmata Xbox Series X", "Pragmata Switch 2", "Pragmata PS4"]:
            with self.subTest(text=text): self.assertEqual(match_product(text,URL,"pragmata"),"reject")
    def test_digital_and_non_game_products(self):
        for part in ["Digital", "Account", "Steam key", "rental", "DLC", "code in box", "preorder bonus", "steelbook only", "no disc", "empty case", "statue", "demo"]:
            with self.subTest(part=part): self.assertEqual(match_product("Pragmata PS5 "+part,URL,"pragmata"),"reject")
    def test_buyback(self): self.assertEqual(match_product("Pragmata PS5 BUYBACK (SELL)",URL,"pragmata"),"reject")
    def test_mixed_platform_is_not_exact(self): self.assertEqual(match_product("Pragmata PS5 Xbox",URL,"pragmata"),"possible")
    def test_no_platform_is_possible(self): self.assertEqual(match_product("Pragmata","https://store.example/product/abc","pragmata"),"possible")
    def test_url_can_establish_platform(self): self.assertEqual(match_product("Pragmata",URL,"pragmata"),"exact")
    def test_url_cannot_replace_wrong_primary_title(self): self.assertEqual(match_product("Another game PS5",URL,"pragmata"),"reject")
    def test_wanted_rejected(self): self.assertEqual(match_product("WTB Pragmata PS5",URL,"pragmata"),"reject")

class BudgetTests(unittest.TestCase):
    def test_4000_inclusive(self): self.assertTrue(budget_decision(listing("4000"),CFG)[0])
    def test_4000_01_rejected(self): self.assertFalse(budget_decision(listing("4,000.01"),CFG)[0])
    def test_4050_rejected(self): self.assertFalse(budget_decision(listing("4,050.00"),CFG)[0])
    def test_missing_rejected(self): self.assertFalse(budget_decision(listing("Not verified"),CFG)[0])
    def test_foreign_currency_rejected(self): self.assertFalse(budget_decision(listing("30",currency="EUR"),CFG)[0])
    def test_nonprices_rejected(self):
        for text in ["NaN","Infinity","-2","0","3999-4499","3.9k","3,9,99","3999 with coupon", "1e3"]:
            with self.subTest(text=text): self.assertIsNone(price_number(text))
    def test_indian_grouping_supported(self): self.assertEqual(str(price_number("1,23,456.00")),"123456.00")
    def test_price_within_cap_is_not_stock_proof(self): self.assertIsNone(event_for(listing(status="out_of_stock"),{},1,CFG))
    def test_unknown_stock_no_alert(self): self.assertIsNone(event_for(listing(status="unknown"),{},1,CFG))
    def test_backorder_no_alert(self): self.assertIsNone(event_for(listing(status="backorder"),{},1,CFG))
    def test_missing_price_no_alert(self): self.assertIsNone(event_for(listing("Not verified"),{},1,CFG))
    def test_possible_platform_no_alert(self): self.assertIsNone(event_for(listing(match="possible"),{},1,CFG))
    def test_old_game_guard(self): self.assertIsNone(event_for(listing(title="Elden Ring SOTE PS5"),{},1,CFG))
    def test_first_qualifying_offer_notified(self): self.assertEqual(event_for(listing(),{},1,CFG),"IN-STOCK LEAD")
    def test_price_crosses_cap_without_restock(self):
        h={}; x=listing("4050")
        self.assertIsNone(event_for(x,h,1,CFG))
        x.price="4000"
        self.assertEqual(event_for(x,h,2,CFG),"IN-STOCK LEAD")
        acknowledge(x,h,"IN-STOCK LEAD")
        self.assertIsNone(event_for(x,h,3,CFG))
    def test_rises_then_reenters_budget(self):
        h={}; x=listing("3999"); event_for(x,h,1,CFG); acknowledge(x,h,"IN-STOCK LEAD")
        x.price="4050"; self.assertIsNone(event_for(x,h,2,CFG))
        x.price="3999"; self.assertEqual(event_for(x,h,3,CFG),"IN-STOCK LEAD")
    def test_unknown_price_does_not_rearm(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,"IN-STOCK LEAD")
        x.price="Not verified"; event_for(x,h,2,CFG)
        x.price="3900"; self.assertIsNone(event_for(x,h,3,CFG))
    def test_restock_still_alerts(self):
        h={}; x=listing(); event_for(x,h,1,CFG); acknowledge(x,h,"IN-STOCK LEAD")
        x.status="out_of_stock"; event_for(x,h,2,CFG)
        x.status="in_stock"; self.assertEqual(event_for(x,h,3,CFG),"IN-STOCK LEAD")

class PragmataParserTests(unittest.TestCase):
    def test_html_current_sale_price(self):
        html=page('<p class="price"><del><span class="amount">4999</span></del><ins><span class="amount">3999</span></ins></p><p class="stock in-stock">In stock</p>')
        x=parse_html(html,SOURCE,URL)[0]
        self.assertEqual((x.price,x.status),("3,999.00","in_stock"))
    def test_price_range_rejected(self):
        html=page('<p class="price"><span class="amount">3999</span> - <span class="amount">4499</span></p><p class="stock in-stock">In stock</p>')
        x=parse_html(html,SOURCE,URL)[0]
        self.assertEqual(x.price,"Not verified"); self.assertIsNone(event_for(x,{},1,CFG))
    def test_account_in_purchase_description(self):
        self.assertEqual(parse_html(page('<p>Shared account, no physical disc</p>'),SOURCE,URL),[])
    def test_shopify_isolates_purchase_variants(self):
        data={"title":"Pragmata PS5","variants":[
            {"id":1,"title":"BUYBACK (SELL)","available":True,"price":300000},
            {"id":2,"title":"Used","available":True,"price":405000},
            {"id":3,"title":"New","available":False,"price":390000}]}
        xs=parse_shopify(data,SOURCE,URL)
        self.assertEqual(len(xs),2)
        self.assertEqual([x.price for x in xs],["4,050.00","3,900.00"])
        self.assertTrue(all(event_for(x,{},1,CFG) is None for x in xs))
    def test_shopify_under_cap_variant(self):
        x=parse_shopify({"title":"Pragmata PS5","variants":[{"id":1,"title":"Used","available":True,"price":399900}]},SOURCE,URL)[0]
        self.assertEqual(event_for(x,{},1,CFG),"IN-STOCK LEAD")
    def test_woo_individual_variants(self):
        import html as h
        vs=[{"variation_id":1,"attributes":{"condition":"Used"},"is_in_stock":True,"display_price":3900},
            {"variation_id":2,"attributes":{"condition":"New"},"is_in_stock":True,"display_price":4499}]
        xs=parse_html(page('<form class="variations_form" data-product_variations="'+h.escape(json.dumps(vs),quote=True)+'"></form>'),SOURCE,URL)
        self.assertEqual([x.price for x in xs],["3,900.00","4,499.00"])
    def test_related_other_game_does_not_count(self):
        self.assertEqual(parse_html(page('<div class="related">Pragmata PS5</div>',title="Other game PS5"),SOURCE,URL),[])
    def test_catalogue_discovery_only_pragmata(self):
        html='<a href="/product/pragmata-ps5/">Pragmata PS5</a><a href="/product/elden-ring-sote-ps5/">Elden Ring SOTE PS5</a>'
        urls,_=discover_html(html,URL,"pragmata")
        self.assertEqual(urls,[URL.rstrip('/')])
    def test_sitemap_only_pragmata(self):
        xml='<urlset><url><loc>'+URL+'</loc></url><url><loc>https://store.example/product/elden-ring-sote-ps5/</loc></url></urlset>'
        _,urls=sitemap_links(xml,SOURCE['base'],target="pragmata")
        self.assertEqual(urls,[URL])
    def test_sitemap_opaque_title(self):
        xml='<urlset><url><loc>https://store.example/product/12345678</loc><title>Pragmata PS5</title></url></urlset>'
        _,urls=sitemap_links(xml,SOURCE['base'],target="pragmata")
        self.assertEqual(len(urls),1)
    def test_scan_source_propagates_target(self):
        class Client:
            def __init__(self,*a): self.calls=0
            def get(self,url): self.calls+=1; return page('<p class="stock in-stock">In stock</p><p class="price"><span class="amount">3900</span></p>')
        xs,report=scan_source(SOURCE,{},CFG,time.time(),client_factory=Client)
        self.assertEqual(xs[0].title,"Pragmata PS5"); self.assertEqual(report['product_pages'],1)

class SwitchIntegrationTests(unittest.TestCase):
    def invoke(self,store,notify,item=None,force=False):
        with patch('sote.engine.scan_source',return_value=([item or listing()],REPORT)), patch('sote.engine.write_run_summary',return_value='offline switch test'):
            return run_scan(CFG,store,notify,force_health=force)
    def test_daily_health_off(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify)
        notify.send.assert_not_called(); self.assertEqual(notify.listing.call_count,1)
    def test_manual_status_still_works(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify,force=True)
        self.assertEqual(notify.send.call_args.args[0],"HEALTH: Pragmata tracker")
    def test_migrates_old_history_preserves_cooldown(self):
        st=empty_state(); st['sources']={'demo':{'known':{'https://store.example/old':1},'cooldown_until':99999999999}}
        st['listings']={'old':{'last_seen':time.time()}}
        store=MemoryStore(st); notify=Mock(); self.invoke(store,notify)
        self.assertEqual(store.state['target'],'pragmata'); self.assertNotIn('old',store.state['listings'])
        self.assertNotIn('known',store.state['sources']['demo'])
        self.assertEqual(store.state['sources']['demo']['cooldown_until'],99999999999)
    def test_not_reset_every_scan(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify); self.invoke(store,notify)
        self.assertEqual(notify.listing.call_count,1)
    def test_failed_delivery_retried(self):
        from sote.notify import NotificationError
        store=MemoryStore(); notify=Mock(); notify.listing.side_effect=NotificationError('offline failure')
        self.assertEqual(self.invoke(store,notify),1)
        notify.listing.side_effect=None; self.assertEqual(self.invoke(store,notify),0)
        self.assertEqual(notify.listing.call_count,2)
    def test_cap_applied_in_actual_scan(self):
        store=MemoryStore(); notify=Mock(); self.invoke(store,notify,listing("4050"))
        notify.listing.assert_not_called(); notify.send.assert_not_called()
        self.invoke(store,notify,listing("4000")); self.assertEqual(notify.listing.call_count,1)
    def test_config_valid_and_no_old_urls(self):
        cfg=read_config(str(Path(__file__).resolve().parents[1]/'config.json'))
        self.assertEqual(cfg['target'],'pragmata'); self.assertEqual(cfg['max_price_inr'],4000)
        self.assertFalse(cfg['daily_health']); self.assertFalse(cfg['alert_possible']); self.assertFalse(cfg['reddit']['enabled'])
        for source in cfg['sources']:
            self.assertEqual(source['target'],'pragmata')
            for url in source.get('products',[])+source.get('catalogues',[]):
                self.assertNotIn('elden',url); self.assertNotIn('erdtree',url)
    def test_config_rejects_bad_cap(self):
        for cap in [False,0,-1,"4000",float('nan')]:
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as d:
                cfg=copy.deepcopy(CFG); cfg['max_price_inr']=cap
                p=Path(d)/'config.json'; p.write_text(json.dumps(cfg))
                with self.assertRaises(ValueError): read_config(str(p))
    def test_summary_says_price_and_budget(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}):
            try:
                os.chdir(d); text=write_run_summary([REPORT],[listing('4050')],[],CFG)
            finally: os.chdir(old)
        self.assertIn('# Pragmata tracker run',text); self.assertIn('above INR 4,000',text)
    def test_discord_branding_has_no_sote_voucher(self):
        d=Discord('https://discord.com/api/webhooks/123456/secret',target='pragmata',max_price_inr=4000)
        r=Mock(status_code=200); r.json.return_value={'id':'123'}; d.session.post=Mock(return_value=r)
        d.listing(listing(),'IN-STOCK LEAD')
        payload=d.session.post.call_args.kwargs['json']; text=json.dumps(payload)
        self.assertEqual(payload['username'],'Pragmata Watcher')
        self.assertNotIn('SOTE',text); self.assertNotIn('DLC voucher',text)
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})

if __name__=='__main__': unittest.main()
