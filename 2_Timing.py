from profitview import Link, logger
import threading 
import time 


class Pr:
	INTERVAL = 3


class Trading(Link):
	
	def on_start(self):
        self.repeated_update()
		
	def repeated_update(self): 
		then = time.time()
		self.update_signal()
		threading.Timer(Pr.INTERVAL - (time.time() - then), self.repeated_update).start()
	
	def update_signal(self):  
		logger.info(f"Updating at {time.time()%100:.1f}")