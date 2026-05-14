class Electrolyzer:
    def __init__(self, data):
        self.capex      = data['capex']
        self.lifetime   = data['lifetime']
        self.eff        = data['eff']
        self.type       = data['type']
        self.qrate      = data['qrate']