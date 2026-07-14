class Electrolyzer:
    def __init__(self, data):
        self.capex      = data['capex']
        self.lifetime   = data['lifetime']
        efficiency      = data['eff']
        self.eff        = efficiency / 100 if efficiency > 1 else efficiency
        self.type       = data['type']
        self.qwater     = data['qwater']
