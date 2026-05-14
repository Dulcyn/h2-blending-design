class Electrolyzer:
    def __init__(self, data):
        self.capex      = data['capex']
        self.lifetime   = data['lifetime']
        self.efficiency = data['eff']