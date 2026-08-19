"""Manual LEAN port of the 20/50 SMA showcase.

Not a hidden DSL — this is the documented mapping. Default fill model
on daily equity + SetHoldings in OnData is next-bar open. Same-bar close
needs ImmediateFillModel (or equivalent) and is a different port. Record
which one you used in engine.json.

Don't collapse those two mappings into one function.
"""

ALGORITHM = r'''
from AlgorithmImports import *

class SmaCrossoverPort(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2022, 1, 3)
        self.SetEndDate(2022, 4, 25)
        self.SetCash(10000)
        self.symbol = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.fast = self.SMA(self.symbol, 20)
        self.slow = self.SMA(self.symbol, 50)

    def OnData(self, data):
        if not (self.fast.IsReady and self.slow.IsReady):
            return
        if self.fast.Current.Value > self.slow.Current.Value:
            self.SetHoldings(self.symbol, 1)
        else:
            self.Liquidate(self.symbol)
'''
