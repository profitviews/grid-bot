from profitview import Link, logger
import threading 
import time 


class Pr:
	INTERVAL = 60
	VENUE = 'BitMEX'
	SYMBOL = 'XBTUSD'
	TICK = 0.5          # Minimum increment of price
	RUNGS = 5
	LOT = 100           # Minimum tradable size
	SIZE = 1*LOT
	LIMIT = 3*LOT
	
 
class Trading(Link):
	
    def quote_update(self, src, sym, data):
		self.quoted = True
		self.bid = data['bid'][0] 
		self.ask = data['ask'][0]

    def on_start(self):
		self.quoted = False
		while not self.quoted: time.sleep(1)  # Wait until there's a quote
        self.repeated_update()
		
	def repeated_update(self):
		then = time.time()
		self.update_signal()
		threading.Timer(Pr.INTERVAL - time.time() + then, self.repeated_update).start()
	
	def update_signal(self):
		self.cancel_order(Pr.VENUE)
			
		net = self.get_net_position()
		inc = self.get_increment()
		
		for rung in range(1, Pr.RUNGS + 1):
			if net > -Pr.LIMIT:  
				self.create_limit_order(Pr.VENUE, Pr.SYMBOL, side='Sell', size=Pr.SIZE, 
										price=self.rung_price('Sell', rung, inc))
			if net < Pr.LIMIT: 
				self.create_limit_order(Pr.VENUE, Pr.SYMBOL, side='Buy', size=Pr.SIZE,
										price=self.rung_price('Buy', rung, inc))
		
	def get_net_position(self):
		p = self.fetch_positions(Pr.VENUE)
		if p['data']: 
			return p['data'][0]['pos_size']
		else:
			return 0
		
	def get_increment(self):
		candles = self.fetch_candles(Pr.VENUE, sym=Pr.SYMBOL, level='1m')['data']
		# 1/4 of the range = (mx - mn)/4 ≈ std dev.
		max_of_range = max(d['high'] for d in candles)
		min_of_range = min(d['low'] for d in candles)
		return (max_of_range - min_of_range)/4.0

	def rung_price(self, side, rung, increment):
		if side == 'Sell': 
			price = self.ask + rung*increment
		else: 
			price = self.bid - rung*increment
			
		return round_to_tick(price)
		
		
def round_to_tick(price, tick=Pr.TICK):
	return round(price/tick)*tick