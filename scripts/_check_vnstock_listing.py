"""Check vnstock listing/symbols endpoint for industry data."""
from vnstock import Vnstock

stock = Vnstock().stock(source='KBS')

# Try listing data
try:
    df = stock.listing.symbols_by_exchange('HOSE')
    print('Listing columns:', list(df.columns))
    hpg = df[df['symbol'] == 'HPG']
    if len(hpg):
        row = hpg.to_dict('records')[0]
        for k, v in row.items():
            if any(w in str(k).lower() for w in ['industry', 'sector', 'icb', 'nganh', 'group']):
                print(f'  {k}: {v}')
    else:
        print('HPG not in listing')
except Exception as e:
    print(f'Listing error: {e}')

# Try company profile alternative
try:
    df2 = stock.company.profile()
    print('\nProfile columns:', list(df2.columns)[:20])
    if len(df2):
        row = df2.to_dict('records')[0]
        for k, v in row.items():
            if any(w in str(k).lower() for w in ['industry', 'sector', 'icb', 'nganh', 'group', 'type']):
                print(f'  {k}: {v}')
except Exception as e:
    print(f'Profile error: {e}')
