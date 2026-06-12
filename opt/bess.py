class Battery:
    def __init__(self, data):
        self.capexP     = data['capex_power']
        self.capexE     = data['capex_energy']
        self.opex       = data['opex']
        self.lifetime   = data['lifetime']
        self.E0         = data['E0']
        self.eff        = data['eff']
        self.Emax       = 40
        self.E          = 20