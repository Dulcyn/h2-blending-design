class General:
    def __init__(self, data):
        self.lifetime   = data['lifetime']
        self.αh2        = data['h2_percentage']
        self.r          = data['discount_rate']
        self.timestep   = data['timestep']
        
