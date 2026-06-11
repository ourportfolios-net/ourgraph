"""Check vnstock listing for industry data using new API."""
from vnstock import Vnstock

try:
    stock = Vnstock().stock(symbol='HPG', source='KBS')
    df = stock.listing.symbols_by_exchange('HOSE')
    print('Listing columns:', list(df.columns))
    hpg = df[df['symbol'] == 'HPG']
    if len(hpg):
        row = hpg.to_dict('records')[0]
        print('HPG listing row:')
        for k, v in row.items():
            print(f'  {k}: {v}')
    else:
        print('HPG not found')
except Exception as e:
    print(f'Error: {e}')
