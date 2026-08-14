class Battery:
    def __init__(self, data):
        self.capex     = data['capex']
        self.opex       = data['opex']
        self.lifetime   = data['lifetime']
        self.E0         = data['E0']
        self.eff        = data['eff']
        self.crate      = data['crate']
        self.eff_ds     = data['eff_ds']
        self.eff_ch     = data['eff_ch']
        self.socmin     = data['socmin']
        self.bigM      = data['bigM']