from profitview import Link, logger, http
import threading 
import time 
import json
import builtins


class Pr:
	"""Constant parameters for the algo"""
	INTERVAL = 60
	VENUE = 'BitMEX'
	SYMBOL = 'XBTUSD'
	RUNGS = 5
	MULT = .1
	BASE_SIZE = 120  # In US$
	SIZE = 1         # Multiple of BASE_SIZE
	LIMIT = 3        # Multiple of BASE_SIZE
	QUOTE_DELAY = 5


class Trading(Link):
	
    def quote_update(self, src, sym, data): 
        """Event: receive top of book quotes from subscribed symbols"""
		if sym == self.symbol:
			self.quoted = True
			self.bid, self.ask = data['bid'][0], data['ask'][0]

    def fill_update(self, src, sym, data):
		if self.symbol == sym: logger.info(f"{data['side']} of {data['fill_size']} {sym} at {data['fill_price']}") 

    def on_start(self):
		self.quoted = False
		self.symbol = Pr.SYMBOL
		# Get parameters specific to this instrument
		if self.venue_setup():
			logger.info(f"Completed {Pr.VENUE} specific setup")
			logger.info(f"Waiting {Pr.QUOTE_DELAY} seconds for first quotes")
			while not self.quoted: time.sleep(Pr.QUOTE_DELAY)  # Wait until there's a quote
			logger.info(f"Starting to repeat")
			self.repeated_update()
		else: logger.warning(f"No instrument data for {self.symbol} - ending algo")

	def venue_setup(self):
		v = BitMEX(self)
		self.base_size = v.standard_size(self.symbol, Pr.BASE_SIZE)
		self.tick = v.tick(self.symbol)
		self.lot = v.lot(self.symbol)
		
		logger.info(f"Tick size: {self.tick}; Lot size: {self.lot}")
		return self.tick and self.lot  # We have a valid tick and lot size for our symbol
		
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
		
		self.check_new_symbol()
		
		net = self.get_net_position()
		inc = self.get_increment()
		size = round_to_lot(Pr.SIZE*self.base_size, self.lot)
		limit = Pr.LIMIT*self.base_size
		
		# logger.info(f"{net=}, {inc=}, {Pr.SIZE=}, {self.base_size=}, {size=}, {limit=}, {self.ask=}")
		
		logger.info(f"{Pr.RUNGS} x {size} {self.symbol} each {round_to_tick(inc, self.tick)} XBT (net {net:.0f})")
		for rung in range(1, Pr.RUNGS + 1):
			# If the net position goes too far (`Pr.LIMIT`) one way, don't set orders that side
			if net > -limit:
				self.create_limit_order(Pr.VENUE, self.symbol, side='Sell', size=size, 
										price=self.rung_price('Sell', rung, inc))
			if net < limit: 
				self.create_limit_order(Pr.VENUE, self.symbol, side='Buy', size=size,
										price=self.rung_price('Buy', rung, inc))
			time.sleep(.1)  # To avoid rate limits

		
	def definitely_cancel_orders(self):
		"""`cancel_order(self)` sometimes times out"""
		logger.info(f"Cancelling all orders at {Pr.VENUE} of {self.symbol}")
		while self.cancel_order(Pr.VENUE, sym=self.symbol)['error']:  # See https://profitview.net/docs/trading/#cancel-order
			logger.warning(f"Error cancelling orders")
			time.sleep(1)
			
	def check_new_symbol(self):
		if Pr.SYMBOL != self.symbol:
			self.symbol = Pr.SYMBOL
			
	def get_net_position(self):
		"""Get symbol position"""
		p = self.fetch_positions(Pr.VENUE)  # See https://profitview.net/docs/trading/#fetch-open-positions
		if p['data']:
			sp = [d['pos_size'] for d in p['data'] if d['sym'] == self.symbol]
			logger.info(f"Position: {sp[0] if sp else 0}")
			return sp[0] if sp else 0
		
		return 0
		
	def get_increment(self, multiplier=Pr.MULT):
		"""Return the range of prices in the list of 1m candles
		
		See: https://profitview.net/docs/trading/#fetch-candles
		"""
		candles = self.fetch_candles(Pr.VENUE, sym=self.symbol, level='1m')  # Will be 1000 candles
		if candles and not candles['error'] and candles['data']:
			# 1/4 of the range = (mx - mn)/4 ≈ std dev.
			fc = list(filter(None, candles['data']))
			max_of_range = max(d['high'] for d in fc)
			min_of_range = min(d['low'] for d in fc)
			return multiplier*(max_of_range - min_of_range)/4.0
		else: raise RuntimeError("Can't get candles")
									
	def rung_price(self, side, rung, increment):
		if side == 'Sell': price = self.ask + rung*increment
		else: price = self.bid - rung*increment  # side == 'Buy'

		return round_to_tick(price, self.tick)

	
class Venue:  # TODO: page to get all instruments
	def __init__(self, src, instruments, venue):
		# Get parameters specific to this instrument
		self.src = src
		self.instruments = instruments
		self.venue = venue
		self.__current_symbol = None
		self.__current_instrument = None

	def _instrument(self, symbol):
		if symbol != self.__current_symbol:
			instrument_data = [i for i in self.instruments if i['symbol'] == symbol]
			self.__current_instrument = instrument_data[0] if instrument_data else None
			self.__current_symbol = symbol if instrument_data else None 

		return self.__current_instrument
	
	def tick(self, symbol):
		if i := self._instrument(symbol):
			return i['tickSize']
		return None
	
	def lot(self, symbol):
		if i := self._instrument(symbol):
			return i['lotSize']
		return None
	
	def standard_size(self, symbol, dollar_amount):
		"""Return the number of lots that will appoximately match the dollar amount given for the symbol passed

		Implemented in venue specific classes
		"""
	

class BitMEX(Venue):
	NAME = 'BitMEX'
	INSTRUMENT_ENDPOINT = 'instrument'
	INSTRUMENT_PAGE_SIZE = 500
	ALGO_PARAMETERS = { 'tickSize': 'float'
					  , 'lotSize': 'int'
					  , 'markPrice': 'float'
					  , 'isInverse': 'bool'
					  , 'multiplier': 'float'
					  , 'settlCurrency': 'str'
					  , 'symbol': 'str'
					  }

	def __type_parameters(self, instruments):
		typed_instruments = []
		for i in instruments:
			ti = {}
			for p, v in BitMEX.ALGO_PARAMETERS.items():
				ti[p] = getattr(builtins, v)(i[p]) if i[p] else i[p]
			typed_instruments.append(ti)
		return typed_instruments

	def __init__(self, trading):
		instrument_count = 0
		all_instruments_data = []
		instrument_meta_data = {}
		self.trading = trading

		while True:  # Max of 500 results per call, so paginate
			         # See: https://www.bitmex.com/api/explorer/#!/Instrument/Instrument_get
			instruments = trading.call_endpoint(
				self.NAME,
				self.INSTRUMENT_ENDPOINT,
				'public',
				method='GET', params={
					'count': 500, 
					'start': instrument_count,
					'columns': json.dumps([*self.ALGO_PARAMETERS])
				})
			all_instruments_data += instruments['data']
			current_count = len(instruments['data'])
			instrument_count += current_count
			logger.info(f"{instrument_count=}")
			if current_count < self.INSTRUMENT_PAGE_SIZE: break
			time.sleep(.1)  # To avoid rate limits
		
		super().__init__(instruments['src'], self.__type_parameters(all_instruments_data), self.NAME)
		
	def standard_size(self, symbol, dollar_amount):
		d = self._instrument(symbol)
		m = d['markPrice']

		if d['isInverse']: m = 1/m
		mm = abs(float(d['multiplier']))*m
		
		xbtparams = self.trading.call_endpoint(
			Pr.VENUE,
			'instrument',
			'public',
			method='GET', params={
				'symbol': 'XBT', 'columns': 'markPrice'
		})
		xbtMark = float(xbtparams['data'][0]['markPrice'])
		
		mark = xbtMark/1e8 if d['settlCurrency'] == 'XBt' else 0.000001  # USDt in $
		minimum_dollar_size = int(d['lotSize'])*mark*mm
		assert(dollar_amount > minimum_dollar_size)
		dollar_multiple = dollar_amount//minimum_dollar_size;
		lot = self.lot(symbol)
		# logger.info(f"{dollar_amount=}, {minimum_dollar_size=}, {mark=}, {lot=}, {dollar_multiple=}, {lot*dollar_multiple=}")
		return dollar_multiple*lot
	

def round_to_tick(price, tick):
	"""Round `price` to an exact multiple of `tick`"""
	return round(price/tick)*tick

def round_to_lot(size, lot):
	"""Round `price` to an exact multiple of `tick`"""
	return round(size/lot)*lot