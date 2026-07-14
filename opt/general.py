class General:
    def __init__(self, data):
        self.lifetime   = data['lifetime']
        self.αh2        = data['h2_percentage']
        discount_rate   = data['discount_rate']
        self.r          = discount_rate / 100 if discount_rate > 1 else discount_rate
        self.timestep   = data['timestep']
        self.days_per_year = data.get('days_per_year', 365)

class Sets:
    def __init__(self, horizon, prob):
        self.Ωt = range(horizon)  # Time steps
        self.Ωs = list(prob.keys())  # Scenarios
        self.prob = prob  # Scenario probabilities
        self.year = int(365 * 24/ horizon)  # Number of years based on the horizon
