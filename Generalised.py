from profitview import Link, logger
import threading 
import time 

class Pr:
	"""Constant parameters for the algo"""
	INTERVAL = 300
	VENUE = 'BitMEX'
	SYMBOL = 'XBTUSD'
	RUNGS = 5
	MULT = .8
	SIZE = 10
	LIMIT = 20
	
 
class Venue:
	def __init__(self, venue, instrument_data):
		self.instruments = instrument_data
		self.src = self.instruments['src']
		self.venue_id = self.instruments['venue_id']

	def instrument(self, symbol):
		return [i for i in self.instruments['data'] if i['symbol'] == symbol][0]


def round_to_tick(price, tick):
	"""Round `price` to an exact multiple of `tick`"""
	logger.info(f"{price=} {tick=}")
	return round(price/tick)*tick

	
class Trading(Link):
	
    def quote_update(self, src, sym, data): 
        """Event: receive top of book quotes from subscribed symbols"""
		self.quoted = True
		self.bid, self.ask = data['bid'][0], data['ask'][0]

    def fill_update(self, src, sym, data):
		logger.info(f"{data['side']} of {data['fill_size']} {Pr.SYMBOL} at {data['fill_price']}")
		
    def on_start(self):
		self.quoted = False
		instrument_data = self.call_endpoint(
			Pr.VENUE,
			'instrument',
			'public',
			method='GET', params={})
		logger.info(f"Getting venue data for {Pr.VENUE}")
		v = Venue(Pr.VENUE, instrument_data)
		logger.info(f"Getting instrument data for {Pr.SYMBOL}")
		i = v.instrument(Pr.SYMBOL)
		logger.info("Got instrument data")
		self.tick = float(i['tickSize'])
		self.lot = int(i['lotSize'])
		logger.info("Quoted" if self.quoted else "Not quoted")
		while not self.quoted: time.sleep(1)  # Wait until there's a quote
		logger.info(f"Starting to repeat")
        self.repeated_update()
		
	def repeated_update(self):
		"""Run `update_signal(self)` every `interval` seconds
		
		Note: `update_signal(self)` must take less than `interval` seconds
		"""
		try:  # On an exception the repetion will end
			then = time.time()
			self.update_signal()
			threading.Timer(Pr.INTERVAL - time.time() + then, self.repeated_update).start()
		except Exception as e:
			logger.warning("Exception thrown: cancelling all orders")
			self.definitely_cancel_orders()
			
			logger.error(f"Exception {e=}, {type(e)=} - repeated_update ending", exc_info=True)
	
	def update_signal(self):
		"""Cancel open orders and enter some more"""
		self.definitely_cancel_orders()				
			
		net = self.get_net_position()
		inc = self.get_increment()
		size = Pr.SIZE*self.lot
		limit = Pr.LIMIT*self.lot
		
		logger.info(f"{Pr.RUNGS} x {Pr.SIZE} {Pr.SYMBOL} each {round_to_tick(inc, self.tick)} XBT (net {net:.0f})")
		for rung in range(1, Pr.RUNGS + 1):
			# If the net position goes too far (`Pr.LIMIT`) one way, don't set orders that side
			if net > -limit:  
				self.create_limit_order(Pr.VENUE, Pr.SYMBOL, side='Sell', size=size, 
										price=self.rung_price('Sell', rung, inc))
			if net < limit: 
				self.create_limit_order(Pr.VENUE, Pr.SYMBOL, side='Buy', size=size,
										price=self.rung_price('Buy', rung, inc))
		
	def definitely_cancel_orders(self):
		"""`cancel_order(self)` sometimes times out"""
		while self.cancel_order(Pr.VENUE)['error']:  # See https://profitview.net/docs/trading/#cancel-order
			logger.warning(f"Error cancelling orders")
			time.sleep(1)
			
	def get_net_position(self):
		"""Get `Pr.SYMBOL` position
		
		Assumes the trader holds positions in no other symbols 
		"""
		p = self.fetch_positions(Pr.VENUE)  # See https://profitview.net/docs/trading/#fetch-open-positions
		if p['data']: 
			return p['data'][0]['pos_size']
		else:
			return 0
		
	def get_increment(self, multiplier=Pr.MULT):
		"""Return the range of prices in the list of 1m candles
		
		See: https://profitview.net/docs/trading/#fetch-candles
		"""
		candles = self.fetch_candles(Pr.VENUE, sym=Pr.SYMBOL, level='1m')  # Will be 1000 candles
		if candles and not candles['error'] and candles['data']:
			# 1/4 of the range = (mx - mn)/4 ≈ std dev.
			fc = list(filter(None, candles['data']))
			max_of_range = max(d['high'] for d in fc)
			min_of_range = min(d['low'] for d in fc)
			return multiplier*(max_of_range - min_of_range)/4.0
		else: raise RuntimeError("Can't get candles")
									
	def rung_price(self, side, rung, increment):
		if side == 'Sell': 
			price = self.ask + rung*increment
		else: 
			price = self.bid - rung*increment
			
		return round_to_tick(price, self.tick)
