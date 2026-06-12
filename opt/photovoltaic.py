class Photovoltaic:
    def __init__(self, data):
        self.capex      = data['capex']
        self.opex       = data['opex']
        self.lifetime   = data['lifetime']
        self.eff        = data['eff']