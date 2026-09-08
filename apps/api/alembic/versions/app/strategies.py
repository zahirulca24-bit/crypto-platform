
from typing import Dict, Any, List

class Strategy:
    name: str
    version: str

    def on_candle_closed(self, candles: List[dict]) -> Dict[str, Any]:
        raise NotImplementedError

class RSITransitionStrategy(Strategy):
    name = 'rsi_transition'
    version = '1.0.0'

    def __init__(self, length=14, overbought=70, oversold=30):
        self.length = int(length)
        self.overbought = float(overbought)
        self.oversold = float(oversold)

    def on_candle_closed(self, candles: List[dict]) -> Dict[str, Any]:
        if len(candles) < self.length + 2:
            return {'decision': 'HOLD', 'reason': 'not_enough_data', 'indicator_values': {}}
        
        from indicators import calculate_rsi
        close_prices = [float(c['close']) for c in candles]
        rsi = calculate_rsi(close_prices, self.length)
        if rsi is None or len(rsi) < 2 or rsi[-1] is None or rsi[-2] is None:
            return {'decision': 'HOLD', 'reason': 'not_enough_rsi', 'indicator_values': {}}
        
        current_rsi = rsi[-1]
        previous_rsi = rsi[-2]

        indicator_values = {
            'previous_rsi': previous_rsi,
            'current_rsi': current_rsi
        }

        if previous_rsi > self.oversold and current_rsi <= self.oversold:
            return {'decision': 'BUY', 'reason': 'rsi_crossed_below_oversold', 'indicator_values': indicator_values}
        elif previous_rsi < self.overbought and current_rsi >= self.overbought:
            return {'decision': 'SELL', 'reason': 'rsi_crossed_above_overbought', 'indicator_values': indicator_values}
        
        return {'decision': 'HOLD', 'reason': 'no_signal', 'indicator_values': indicator_values}


class MACDCrossoverStrategy(Strategy):
    name = 'macd_crossover'
    version = '1.0.0'

    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = int(fast)
        self.slow = int(slow)
        self.signal = int(signal)

    def on_candle_closed(self, candles: List[dict]) -> Dict[str, Any]:
        if len(candles) < self.slow + self.signal + 1:
            return {'decision': 'HOLD', 'reason': 'not_enough_data', 'indicator_values': {}}
        
        from indicators import calculate_macd
        close_prices = [float(c['close']) for c in candles]
        macd_res = calculate_macd(close_prices, self.fast, self.slow, self.signal)
        if macd_res is None:
            return {'decision': 'HOLD', 'reason': 'macd_calculation_failed', 'indicator_values': {}}
            
        macd_line = macd_res['macd']
        sig_line = macd_res['signal']
        
        if len(macd_line) < 2 or macd_line[-1] is None or macd_line[-2] is None or sig_line[-1] is None or sig_line[-2] is None:
            return {'decision': 'HOLD', 'reason': 'not_enough_macd', 'indicator_values': {}}
            
        current_macd = macd_line[-1]
        previous_macd = macd_line[-2]
        current_sig = sig_line[-1]
        previous_sig = sig_line[-2]

        indicator_values = {
            'previous_macd': previous_macd,
            'previous_signal': previous_sig,
            'current_macd': current_macd,
            'current_signal': current_sig,
            'histogram': current_macd - current_sig
        }

        if previous_macd <= previous_sig and current_macd > current_sig:
            return {'decision': 'BUY', 'reason': 'macd_crossed_above_signal', 'indicator_values': indicator_values}
        elif previous_macd >= previous_sig and current_macd < current_sig:
            return {'decision': 'SELL', 'reason': 'macd_crossed_below_signal', 'indicator_values': indicator_values}
        
        return {'decision': 'HOLD', 'reason': 'no_signal', 'indicator_values': indicator_values}


class MACrossoverStrategy(Strategy):
    name = 'ma_crossover'
    version = '1.0.0'

    def __init__(self, fast_len=10, slow_len=50, ma_type='ema'):
        self.fast_len = int(fast_len)
        self.slow_len = int(slow_len)
        self.ma_type = str(ma_type)

    def on_candle_closed(self, candles: List[dict]) -> Dict[str, Any]:
        if len(candles) < self.slow_len + 2:
            return {'decision': 'HOLD', 'reason': 'not_enough_data', 'indicator_values': {}}
            
        from indicators import calculate_ema, calculate_sma
        close_prices = [float(c['close']) for c in candles]
        
        if self.ma_type == 'ema':
            fast_ma = calculate_ema(close_prices, self.fast_len)
            slow_ma = calculate_ema(close_prices, self.slow_len)
        else:
            fast_ma = calculate_sma(close_prices, self.fast_len)
            slow_ma = calculate_sma(close_prices, self.slow_len)
            
        if fast_ma is None or slow_ma is None or fast_ma[-1] is None or fast_ma[-2] is None or slow_ma[-1] is None or slow_ma[-2] is None:
            return {'decision': 'HOLD', 'reason': 'ma_calculation_failed', 'indicator_values': {}}
            
        current_fast = fast_ma[-1]
        previous_fast = fast_ma[-2]
        current_slow = slow_ma[-1]
        previous_slow = slow_ma[-2]

        indicator_values = {
            'previous_fast': previous_fast,
            'previous_slow': previous_slow,
            'current_fast': current_fast,
            'current_slow': current_slow,
            'ma_type': self.ma_type
        }

        if previous_fast <= previous_slow and current_fast > current_slow:
            return {'decision': 'BUY', 'reason': 'fast_ma_crossed_above_slow_ma', 'indicator_values': indicator_values}
        elif previous_fast >= previous_slow and current_fast < current_slow:
            return {'decision': 'SELL', 'reason': 'fast_ma_crossed_below_slow_ma', 'indicator_values': indicator_values}
        
        return {'decision': 'HOLD', 'reason': 'no_signal', 'indicator_values': indicator_values}
