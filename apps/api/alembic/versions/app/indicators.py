
def calculate_sma(series, length):
    if len(series) < length: return None
    smas = []
    for i in range(len(series)):
        if i < length - 1:
            smas.append(None)
        else:
            smas.append(sum(series[i-length+1:i+1]) / length)
    return smas

def calculate_ema(series, length):
    if len(series) < length: return None
    emas = []
    alpha = 2 / (length + 1)
    for i in range(len(series)):
        if i < length - 1:
            emas.append(None)
        elif i == length - 1:
            emas.append(sum(series[:length]) / length)
        else:
            emas.append(alpha * series[i] + (1 - alpha) * emas[-1])
    return emas

def calculate_macd(series, fast=12, slow=26, signal=9):
    fast_ema = calculate_ema(series, fast)
    slow_ema = calculate_ema(series, slow)
    if slow_ema is None: return None
    macd_line = []
    for f, s in zip(fast_ema, slow_ema):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)
    
    # Calculate signal line which is EMA of MACD
    valid_macd = [x for x in macd_line if x is not None]
    if len(valid_macd) < signal: return None
    sig_line_valid = calculate_ema(valid_macd, signal)
    
    sig_line = [None] * (len(macd_line) - len(sig_line_valid)) + sig_line_valid
    
    return {'macd': macd_line, 'signal': sig_line}

def calculate_rsi(series, length=14):
    if len(series) < length + 1: return None
    changes = [series[i] - series[i-1] for i in range(1, len(series))]
    
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    
    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length
    
    rsis = [None] * length
    if avg_loss == 0:
        rsis.append(100.0 if avg_gain > 0 else 0.0)
    else:
        rs = avg_gain / avg_loss
        rsis.append(100 - (100 / (1 + rs)))
        
    for i in range(length, len(changes)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
        if avg_loss == 0:
            rsis.append(100.0 if avg_gain > 0 else 0.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100 - (100 / (1 + rs)))
            
    return rsis
