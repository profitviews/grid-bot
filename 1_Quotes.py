from profitview import Link, logger
import time

class Trading(Link):
  def quote_update(self, src, sym, data):
		logger.info(f"{time.time()*1000 - data['time']:.1f}")