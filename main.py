# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, math, os
from datetime import datetime, timedelta
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

PROGRAM_NAME = "AYNA RSI REGRESYON V5.3 KIVY"
PIP_VALUE = 0.01
RSI_PERIOD = 14
TP_PIP, SL_PIP = 15, 7
LONG_MOMENTUM_MIN, LONG_MOMENTUM_MAX = 55, 69
SHORT_MOMENTUM_MIN, SHORT_MOMENTUM_MAX = 31, 45
RSI_OVERBOUGHT, RSI_OVERSOLD = 72, 28
MIN_RSI_CHANGE = 1.0
ADAPTIVE_BLOCK_HOURS = (1, 2, 4)
ADAPTIVE_BLOCK_BARS = (60, 120, 240)
REG_SHORT, REG_LONG, REG_WINDOW = 6, 20, 20
BAND_STD, OUTSIDE_TOLERANCE = 1.0, 0.15
VOLUME_MODE_CUMULATIVE, VOLUME_MODE_BAR = "KUMULATIF", "BAR"
CHANNEL_MODE_ROLLING, CHANNEL_MODE_FULL_DAY = "KAYAN CANLI KANAL", "TAM GUN KANALI"

def mean(v): return sum(v) / len(v) if v else 0.0
def stddev(v):
    if not v: return 0.0
    m = mean(v)
    return math.sqrt(sum((x-m)**2 for x in v)/len(v))
def linreg(v):
    n=len(v)
    if n<2: return 0.0, list(v)
    sx=(n-1)*n/2; sy=sum(v); sxx=(n-1)*n*(2*n-1)/6
    sxy=sum(i*x for i,x in enumerate(v)); den=n*sxx-sx*sx
    m=0.0 if den==0 else (n*sxy-sx*sy)/den
    b=(sy-m*sx)/n
    return m,[m*i+b for i in range(n)]
def slope(v): return linreg(v)[0]
def calc_rsi(prices, period=RSI_PERIOD):
    if len(prices)<period+1: return None
    s=prices[-(period+1):]; gains=[]; losses=[]
    for i in range(1,len(s)):
        d=s[i]-s[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag,al=mean(gains),mean(losses)
    if al==0: return 100.0 if ag>0 else 50.0
    rs=ag/al
    return 100-100/(1+rs)

def parse_time(x):
    x=x.strip()
    for f in ("%H:%M:%S","%H:%M","%Y-%m-%d %H:%M:%S","%d.%m.%Y %H:%M:%S"):
        try:
            d=datetime.strptime(x,f)
            return datetime(2000,1,1,d.hour,d.minute,d.second) if f.startswith("%H") else d
        except ValueError: pass
    return None

def read_csv_data(path):
    text=Path(path).read_text(encoding="utf-8-sig")
    delim=";" if text[:2000].count(";")>text[:2000].count(",") else ","
    rows=list(csv.reader(text.splitlines(),delimiter=delim))
    if not rows: raise ValueError("CSV boş")
    first=[x.strip().lower() for x in rows[0]]
    has_header=any(k in first for k in ("fiyat","price","close","hacim","volume","saat","time"))
    headers=first if has_header else []
    data=rows[1:] if has_header else rows
    def idx(names):
        for n in names:
            if n in headers: return headers.index(n)
        return None
    pi,vi,ti=idx(("fiyat","price","close","last")),idx(("hacim","volume","vol","lot")),idx(("saat","time","timestamp","datetime","tarih","date"))
    out=[]; rtc=0
    for row in data:
        nums=[]
        for j,c in enumerate(row):
            try: nums.append((j,float(c.strip().replace(",","."))))
            except: pass
        pidx=pi if pi is not None else (nums[0][0] if nums else None)
        if pidx is None or pidx>=len(row): continue
        try: p=float(row[pidx].strip().replace(",","."))
        except: continue
        if p<=0: continue
        if vi is not None and vi<len(row):
            try: vol=float(row[vi].strip().replace(",","."))
            except: vol=0.0
        else: vol=nums[1][1] if len(nums)>1 else 0.0
        t=parse_time(row[ti]) if ti is not None and ti<len(row) else None
        if t: rtc+=1
        out.append((p,vol,t))
    if len(out)<RSI_PERIOD+2: raise ValueError("Yetersiz temiz veri")
    return out, rtc>=RSI_PERIOD+2

class Engine:
    def __init__(self,use_real_time=False):
        self.use_real_time=use_real_time; self.prices=[]; self.bar_volumes=[]; self.raw_volumes=[]; self.times=[]
        self.position=None; self.entry_price=None; self.tp_price=None; self.sl_price=None; self.entry_index=None
        self.entry_reason=""; self.entry_meta={}; self.trades=[]
        self.block_until_time={"LONG":None,"SHORT":None}; self.block_until_bar={"LONG":-1,"SHORT":-1}
        self.stop_streak={"LONG":0,"SHORT":0}; self.last_block_hours={"LONG":0,"SHORT":0}
        self.last_signal="BEKLE"; self.last_result="YOK"; self.last_rsi=None; self.last_drsi=0.0
        self.last_acceleration=0.0; self.last_channel_label="-"; self.last_channel_ratio=0.0
        self.last_confidence=0; self.last_confidence_parts={}
    def reset(self): self.__init__(self.use_real_time)
    def append_data(self,p,v,t=None,mode=VOLUME_MODE_BAR):
        p=float(p); v=float(v)
        if mode==VOLUME_MODE_CUMULATIVE:
            bv=v if not self.raw_volumes else v-self.raw_volumes[-1]
            if bv<0: bv=v
        else: bv=v
        self.prices.append(p); self.raw_volumes.append(v); self.bar_volumes.append(max(0.0,bv)); self.times.append(t)
    def reg_values(self):
        if len(self.prices)<2: return list(self.prices),None,None
        y=self.prices[-min(REG_WINDOW,len(self.prices)):]
        _,fit=linreg(y); sd=stddev([a-b for a,b in zip(y,fit)])
        return fit,[x+sd for x in fit],[x-sd for x in fit]
    def full_day(self):
        if len(self.prices)<2:
            a=[math.nan]*len(self.prices); return a,a[:],a[:]
        _,fit=linreg(self.prices); sd=stddev([a-b for a,b in zip(self.prices,fit)])
        return fit,[x+sd for x in fit],[x-sd for x in fit]
    def rolling(self):
        n=len(self.prices); r=[math.nan]*n; u=r[:]; l=r[:]
        for end in range(1,n):
            y=self.prices[max(0,end-REG_WINDOW+1):end+1]
            _,fit=linreg(y); sd=stddev([a-b for a,b in zip(y,fit)])
            r[end]=fit[-1]; u[end]=fit[-1]+sd; l[end]=fit[-1]-sd
        return r,u,l
    def acceleration(self):
        return 0.0 if len(self.prices)<REG_LONG else slope(self.prices[-REG_SHORT:])-slope(self.prices[-REG_LONG:])
    def channel_status(self,p):
        _,u,l=self.reg_values()
        if not u:return "KANAL HAZIR DEGIL",0.0
        up,lo=u[-1],l[-1]; w=max(up-lo,PIP_VALUE)
        if lo<=p<=up:return "KANAL ICI",0.0
        d=p-up if p>up else lo-p; q=d/w
        return ("KANALA YAKIN" if q<=OUTSIDE_TOLERANCE else "UZAK NOKTA"),q
    def blocked(self,d,i,t):
        if self.use_real_time and t is not None:
            u=self.block_until_time[d]; return u is not None and t<u
        return i<self.block_until_bar[d]
    def block(self,d,i,t):
        self.stop_streak[d]+=1; k=min(self.stop_streak[d],3)-1
        h,b=ADAPTIVE_BLOCK_HOURS[k],ADAPTIVE_BLOCK_BARS[k]; self.last_block_hours[d]=h
        if self.use_real_time and t is not None:self.block_until_time[d]=t+timedelta(hours=h)
        else:self.block_until_bar[d]=i+b
        return h
    def reset_streak(self,d):
        self.stop_streak[d]=0; self.last_block_hours[d]=0; self.block_until_time[d]=None; self.block_until_bar[d]=-1
    def confidence(self,d,r,dr,a,ch):
        p={}
        if d=="LONG": p["RSI"]=35 if r<=RSI_OVERSOLD else 40 if LONG_MOMENTUM_MIN<=r<=LONG_MOMENTUM_MAX and dr>=1 else 20
        else:p["RSI"]=35 if r>=RSI_OVERBOUGHT else 40 if SHORT_MOMENTUM_MIN<=r<=SHORT_MOMENTUM_MAX and dr<=-1 else 20
        p["IVME"]=25 if ((d=="LONG" and a>=0) or (d=="SHORT" and a<=0)) else 8
        p["KANAL"]={"KANAL ICI":25,"KANALA YAKIN":18,"UZAK NOKTA":5}.get(ch,10)
        if len(self.bar_volumes)>=11:
            av=mean(self.bar_volumes[-11:-1]); q=self.bar_volumes[-1]/av if av>0 else 1
            p["HACIM"]=10 if q>=1 else 5
        else:p["HACIM"]=5
        return sum(p.values()),p
    def signal(self,i,t):
        r=calc_rsi(self.prices); pr=calc_rsi(self.prices[:-1]) if len(self.prices)>RSI_PERIOD+1 else None
        self.last_rsi=r
        if r is None or pr is None:return None
        dr=r-pr; self.last_drsi=dr; a=self.acceleration(); self.last_acceleration=a
        ch,qr=self.channel_status(self.prices[-1]); self.last_channel_label=ch; self.last_channel_ratio=qr
        d=reason=None
        if LONG_MOMENTUM_MIN<=r<=LONG_MOMENTUM_MAX and dr>=MIN_RSI_CHANGE:d,reason="LONG","RSI MOMENTUM LONG"
        elif SHORT_MOMENTUM_MIN<=r<=SHORT_MOMENTUM_MAX and dr<=-MIN_RSI_CHANGE:d,reason="SHORT","RSI MOMENTUM SHORT"
        elif r>=RSI_OVERBOUGHT:d,reason="SHORT","RSI ASIRI YUKSEK SHORT"
        elif r<=RSI_OVERSOLD:d,reason="LONG","RSI ASIRI DUSUK LONG"
        if d is None:return None
        if self.blocked(d,i,t):
            self.last_result=f"{d} ENGELLI | {self.last_block_hours.get(d,1) or 1} SAAT YON KILIDI"; return None
        c,parts=self.confidence(d,r,dr,a,ch); self.last_confidence=c; self.last_confidence_parts=parts
        return {"direction":d,"reason":reason,"rsi":r,"drsi":dr,"acceleration":a,"channel":ch,"confidence":c}
    def open(self,s,i):
        d=s["direction"]; p=self.prices[-1]; self.position=d; self.entry_price=p; self.entry_index=i; self.entry_reason=s["reason"]; self.entry_meta=s.copy()
        if d=="LONG":self.tp_price=round(p+TP_PIP*PIP_VALUE,2); self.sl_price=round(p-SL_PIP*PIP_VALUE,2)
        else:self.tp_price=round(p-TP_PIP*PIP_VALUE,2); self.sl_price=round(p+SL_PIP*PIP_VALUE,2)
        self.last_result=f"{d} ACILDI | {p:.2f} | TP {self.tp_price:.2f} | SL {self.sl_price:.2f}"
    def check(self,p,i,t):
        if self.position is None:return False
        result=x=None; d=self.position
        if d=="LONG":
            if p>=self.tp_price:result,x="TP",self.tp_price
            elif p<=self.sl_price:result,x="SL",self.sl_price
        else:
            if p<=self.tp_price:result,x="TP",self.tp_price
            elif p>=self.sl_price:result,x="SL",self.sl_price
        if result is None:return False
        pip=(x-self.entry_price)/PIP_VALUE if d=="LONG" else (self.entry_price-x)/PIP_VALUE
        self.trades.append({"yon":d,"giris":self.entry_price,"cikis":x,"sonuc":result,"pip":pip,"rsi":self.entry_meta.get("rsi"),"guven":self.entry_meta.get("confidence"),"giris_bar":self.entry_index,"cikis_bar":i})
        if result=="SL":info=f"{self.block(d,i,t)} SAAT YASAK"
        else:self.reset_streak(d); info="CEZA SIFIRLANDI"
        self.last_result=f"{d} {result} | {pip:+.1f} PIP | {info}"
        self.position=None; self.entry_price=self.tp_price=self.sl_price=None; self.entry_index=None; self.entry_meta={}
        return True
    def process(self,p,v,t=None,mode=VOLUME_MODE_BAR):
        self.append_data(p,v,t,mode); i=len(self.prices)-1
        if self.check(p,i,t):self.last_signal="BEKLE"; return
        if self.position is not None:self.last_signal="POZISYON TAKIP"; return
        s=self.signal(i,t)
        if s is None:self.last_signal="BEKLE"; return
        self.last_signal=s["direction"]; self.open(s,i)
    def eod(self):
        if self.position is None:return
        d=self.position; x=self.prices[-1]; pip=(x-self.entry_price)/PIP_VALUE if d=="LONG" else (self.entry_price-x)/PIP_VALUE
        self.trades.append({"yon":d,"giris":self.entry_price,"cikis":x,"sonuc":"GUN SONU","pip":pip,"rsi":self.entry_meta.get("rsi"),"guven":self.entry_meta.get("confidence"),"giris_bar":self.entry_index,"cikis_bar":len(self.prices)-1})
        self.last_result=f"{d} GUN SONU | {pip:+.1f} PIP"; self.position=None; self.last_signal="BEKLE"
    def summary(self):
        n=len(self.trades); tp=sum(t["sonuc"]=="TP" for t in self.trades); sl=sum(t["sonuc"]=="SL" for t in self.trades)
        eod=sum(t["sonuc"]=="GUN SONU" for t in self.trades); wins=sum(t["pip"]>0 for t in self.trades); net=sum(t["pip"] for t in self.trades)
        return n,tp,sl,eod,(wins/n*100 if n else 0),net

class Chart(Widget):
    prices=ListProperty([]); volumes=ListProperty([]); reg=ListProperty([]); upper=ListProperty([]); lower=ListProperty([]); trades=ListProperty([])
    def redraw(self,*_):
        self.canvas.clear()
        if len(self.prices)<2:return
        vals=[v for s in (self.prices,self.reg,self.upper,self.lower) for v in s if v is not None and not math.isnan(float(v))]
        if not vals:return
        L,R=self.x+dp(6),self.right-dp(6); B,T=self.y+dp(6),self.top-dp(6); VH=self.height*.22; PB=B+VH+dp(6)
        mn,mx=min(vals),max(vals)
        if mx==mn:mx+=1
        pad=(mx-mn)*.05; mn-=pad; mx+=pad; n=len(self.prices)
        px=lambda i:L+(R-L)*i/max(n-1,1); py=lambda v:PB+(T-PB)*(v-mn)/(mx-mn)
        with self.canvas:
            Color(.1,.1,.1,1); Rectangle(pos=self.pos,size=self.size)
            def draw(s,c,w=1):
                pts=[]
                for i,v in enumerate(s):
                    if i<n and v is not None and not math.isnan(float(v)):pts += [px(i),py(float(v))]
                if len(pts)>=4:Color(*c);Line(points=pts,width=w)
            draw(self.prices,(.95,.95,.95,1),1.2);draw(self.reg,(.2,.65,1,1),1.1);draw(self.upper,(.3,.85,.45,1),1);draw(self.lower,(.3,.85,.45,1),1)
            vmax=max(self.volumes) if self.volumes else 1
            if vmax<=0:vmax=1
            Color(.55,.55,.55,.8); bw=max((R-L)/n*.7,1)
            for i,v in enumerate(self.volumes):Rectangle(pos=(px(i)-bw/2,B),size=(bw,VH*v/vmax))
            for tr in self.trades:
                ib,xb=tr.get("giris_bar"),tr.get("cikis_bar")
                if ib is not None:Color(.2,.9,.3,1) if tr.get("yon")=="LONG" else Color(.95,.3,.3,1);Line(circle=(px(ib),py(tr["giris"]),dp(4)),width=1.3)
                if xb is not None:Color(.2,1,.35,1) if tr.get("sonuc")=="TP" else Color(1,.2,.2,1);Line(rectangle=(px(xb)-3,py(tr["cikis"])-3,6,6),width=1.3)
    def __init__(self,**kw):
        super().__init__(**kw)
        for p in ("pos","size","prices","volumes","reg","upper","lower","trades"):self.bind(**{p:self.redraw})

class Root(BoxLayout):
    def __init__(self,**kw):
        super().__init__(orientation="vertical",spacing=dp(4),padding=dp(4),**kw)
        self.e=Engine(); self.channel_mode=CHANNEL_MODE_FULL_DAY; self.manual_mode=VOLUME_MODE_CUMULATIVE
        h=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(3)); h.add_widget(Label(text=PROGRAM_NAME,bold=True))
        for text,fn in (("RESET",self.reset),("CSV TEST",self.choose_csv),("GEÇMİŞ",self.history)):
            b=Button(text=text,size_hint_x=None,width=dp(85));b.bind(on_release=lambda _,f=fn:f());h.add_widget(b)
        self.add_widget(h)
        g=GridLayout(cols=6,size_hint_y=None,height=dp(42),spacing=dp(3))
        g.add_widget(Label(text="Fiyat"));self.p=TextInput(multiline=False,input_filter="float");g.add_widget(self.p)
        g.add_widget(Label(text="Hacim"));self.v=TextInput(multiline=False,input_filter="float");g.add_widget(self.v)
        self.ms=Spinner(text=VOLUME_MODE_CUMULATIVE,values=(VOLUME_MODE_CUMULATIVE,VOLUME_MODE_BAR));self.ms.bind(text=lambda _,x:setattr(self,"manual_mode",x));g.add_widget(self.ms)
        b=Button(text="BAR EKLE");b.bind(on_release=lambda *_:self.add_bar());g.add_widget(b);self.add_widget(g)
        o=BoxLayout(size_hint_y=None,height=dp(40),spacing=dp(3))
        self.cs=Spinner(text=CHANNEL_MODE_FULL_DAY,values=(CHANNEL_MODE_FULL_DAY,CHANNEL_MODE_ROLLING));self.cs.bind(text=lambda _,x:self.set_channel(x));o.add_widget(self.cs)
        self.add_widget(o);self.chart=Chart();self.add_widget(self.chart)
        self.decision=Label(text="BEKLE",font_size=dp(24),bold=True,size_hint_y=None,height=dp(48));self.add_widget(self.decision)
        self.info=Label(text="Hazır",size_hint_y=None,height=dp(68),halign="center",valign="middle");self.info.bind(size=lambda w,s:setattr(w,"text_size",s));self.add_widget(self.info)
        Clock.schedule_once(lambda *_:self.refresh(),0)
    def set_channel(self,x):self.channel_mode=x;self.refresh()
    def reset(self):self.e=Engine();self.refresh()
    def add_bar(self):
        try:p=float(self.p.text.replace(",","."));v=float(self.v.text.replace(",","."))
        except:return self.msg("HATA","Fiyat ve hacim sayısal olmalı")
        self.e.process(p,v,datetime.now(),self.manual_mode);self.p.text="";self.v.text="";self.cs.text=CHANNEL_MODE_FULL_DAY;self.channel_mode=CHANNEL_MODE_FULL_DAY;self.refresh()
    def choose_csv(self):
        fc=FileChooserListView(path=str(Path.home()),filters=["*.csv","*.CSV"]);box=BoxLayout(orientation="vertical");box.add_widget(fc)
        row=BoxLayout(size_hint_y=None,height=dp(48));ok=Button(text="SEÇ");cancel=Button(text="İPTAL");row.add_widget(ok);row.add_widget(cancel);box.add_widget(row)
        pop=Popup(title="CSV SEÇ",content=box,size_hint=(.96,.92))
        def go(*_):
            if not fc.selection:return
            path=fc.selection[0];pop.dismiss()
            try:
                rows,rt=read_csv_data(path);e=Engine(rt)
                for p,v,t in rows:e.process(p,v,t,VOLUME_MODE_BAR)
                e.eod();self.e=e;self.channel_mode=CHANNEL_MODE_FULL_DAY;self.cs.text=CHANNEL_MODE_FULL_DAY;self.refresh()
                n,tp,sl,eo,wr,net=e.summary();self.msg("TEST SONUCU",f"{os.path.basename(path)}\nİşlem:{n}\nTP:{tp}\nSL:{sl}\nGün sonu:{eo}\nWin:%{wr:.1f}\nNet:{net:+.1f} pip")
            except Exception as ex:self.msg("CSV HATASI",f"{type(ex).__name__}: {ex}")
        ok.bind(on_release=go);cancel.bind(on_release=lambda *_:pop.dismiss());pop.open()
    def history(self):
        box=BoxLayout(orientation="vertical");sv=ScrollView();gl=GridLayout(cols=1,size_hint_y=None);gl.bind(minimum_height=gl.setter("height"))
        for i,t in enumerate(self.e.trades,1):gl.add_widget(Label(text=f"{i}. {t['yon']} | {t['sonuc']} | {t['pip']:+.1f} pip",size_hint_y=None,height=dp(40)))
        sv.add_widget(gl);box.add_widget(sv);b=Button(text="KAPAT",size_hint_y=None,height=dp(48));box.add_widget(b);p=Popup(title="İŞLEM GEÇMİŞİ",content=box,size_hint=(.95,.9));b.bind(on_release=lambda *_:p.dismiss());p.open()
    def msg(self,title,text):
        box=BoxLayout(orientation="vertical",padding=dp(8));box.add_widget(Label(text=text));b=Button(text="TAMAM",size_hint_y=None,height=dp(48));box.add_widget(b);p=Popup(title=title,content=box,size_hint=(.88,.62));b.bind(on_release=lambda *_:p.dismiss());p.open()
    def refresh(self):
        r,u,l=self.e.full_day() if self.channel_mode==CHANNEL_MODE_FULL_DAY else self.e.rolling()
        self.chart.prices=self.e.prices[:];self.chart.volumes=self.e.bar_volumes[:];self.chart.reg=r;self.chart.upper=u;self.chart.lower=l;self.chart.trades=self.e.trades[:]
        d=self.e.position or (self.e.last_signal if self.e.last_signal in ("LONG","SHORT") else "BEKLE");self.decision.text=f"{d} | Güven {self.e.last_confidence}/100"
        self.info.text=f"RSI:{'-' if self.e.last_rsi is None else f'{self.e.last_rsi:.1f}'} | dRSI:{self.e.last_drsi:+.2f} | İvme:{self.e.last_acceleration:+.6f}\nKanal:{self.e.last_channel_label} | Sonuç:{self.e.last_result}"
class AynaApp(App):
    def build(self):Window.clearcolor=(.08,.08,.08,1);self.title=PROGRAM_NAME;return Root()
if __name__=="__main__":AynaApp().run()
