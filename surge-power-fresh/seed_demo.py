"""Add clearly marked example inquiries once, without touching real requests."""
from app import db

examples = [
    ('DEMO — Jordan Example', 'jordan@example.invalid', 'EV charger installation', 'Mesa', 'Demo inquiry: interested in charging at home.', 'new'),
    ('DEMO — Avery Example', 'avery@example.invalid', 'General electrical work', 'Chandler', 'Demo inquiry: would like to discuss an additional circuit.', 'contacted'),
    ('DEMO — Taylor Example', 'taylor@example.invalid', 'EV charger installation', 'Phoenix', 'Demo inquiry: planning a charger installation.', 'qualified'),
]
with db() as con:
    for record in examples:
        if not con.execute('SELECT 1 FROM inquiries WHERE contact=?', (record[1],)).fetchone():
            con.execute('INSERT INTO inquiries(name, contact, service, location, details, stage) VALUES(?,?,?,?,?,?)', record)
print('Demo inquiries ready.')
