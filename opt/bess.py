class Battery:
    def __init__(self, data):
        self.capex     = data['capex']
        self.opex       = data['opex']
        self.lifetime   = data['lifetime']
        self.E0         = data['E0']
        self.eff        = data['eff']
        self.crate      = data['crate']