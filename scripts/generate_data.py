"""Generate deterministic synthetic records. Never use real passengers."""
import json
from pathlib import Path


def passengers():
    rows = []
    for i in range(1, 13):
        rows.append(dict(source_id=f'SRC{i:03}', passenger_id=f'P{i:03}',
                         surname=f'Synthetic{i}', email=f'passenger{i}@example.invalid',
                         email_verified=True, skymiles=f'SYN{i:07}', tier='GOLD',
                         pnr=f'D{i:05}', consent=True, cabin='ECONOMY',
                         special='routine', updated_at='2026-11-15T12:00:00Z'))
    rows[1].update(passenger_id='P001', surname='Synthetic1', skymiles=rows[0]['skymiles'],
                   pnr='D00001', email='passenger1.variant@example.invalid', email_verified=False)
    for i, special in [(3, 'group'), (4, 'medical'), (5, 'minor')]:
        rows[i]['special'] = special
    rows[6]['consent'] = False
    for i in [13,14]:
        rows.append(dict(source_id=f'SRC{i:03}',passenger_id=f'P{i:03}',surname='SharedSynthetic',email=f'group{i}@example.invalid',email_verified=False,skymiles=f'SYN{i:07}',tier='GOLD',pnr='D00888',consent=True,cabin='ECONOMY',special='group',updated_at='2026-11-15T12:00:00Z'))
    return rows


if __name__ == '__main__':
    Path('data').mkdir(exist_ok=True)
    Path('data/synthetic-passengers.json').write_text(json.dumps(passengers(), indent=2)+'\n')
    print('Generated 14 synthetic source records; 13 distinct passenger references')
