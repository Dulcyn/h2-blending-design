class General:
    def __init__(self, data):
        self.lifetime   = data['lifetime']
        self.αh2        = data['h2_percentage']
        discount_rate   = data['discount_rate']
        self.r          = discount_rate / 100 if discount_rate > 1 else discount_rate
        self.timestep   = data['timestep']
        self.days_per_year = data.get('days_per_year', 365)
        
